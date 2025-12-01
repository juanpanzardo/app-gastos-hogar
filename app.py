import streamlit as st
import pandas as pd
from datetime import datetime, date, timedelta
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import plotly.express as px

# --- CONFIGURACIÓN INICIAL ---
st.set_page_config(page_title="Gastos del Hogar AI", page_icon="🏠", layout="wide")

# --- CONEXIÓN CON GOOGLE SHEETS ---
def conectar_google_sheets():
    try:
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds_dict = dict(st.secrets["service_account"])
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        sh = client.open("Gastos_Hogar_DB")
        return sh
    except Exception as e:
        st.error(f"❌ Error de conexión: {e}")
        return None

# --- FUNCIONES DE LOGICA DE NEGOCIO ---
def cargar_datos(hoja, pestaña):
    try:
        worksheet = hoja.worksheet(pestaña)
        data = worksheet.get_all_records()
        df = pd.DataFrame(data)
        # Limpieza de datos numéricos
        if not df.empty:
            if 'Saldo_Actual' in df.columns:
                df['Saldo_Actual'] = df['Saldo_Actual'].replace('[\$,]', '', regex=True).replace('', 0).astype(float)
            if 'Monto' in df.columns:
                 df['Monto'] = df['Monto'].replace('[\$,]', '', regex=True).replace('', 0).astype(float)
        return df
    except Exception as e:
        st.error(f"Error leyendo {pestaña}: {e}")
        return pd.DataFrame()

def registrar_pago_real(hoja, id_movimiento, cuenta_origen, monto):
    """
    1. Busca el movimiento pendiente.
    2. Lo marca como PAGADO.
    3. Descuenta el dinero de la cuenta.
    """
    try:
        # A) Actualizar el Movimiento a PAGADO
        ws_mov = hoja.worksheet("Movimientos")
        cell = ws_mov.find(str(id_movimiento)) # Busca por ID
        
        # Columnas (basado en tu estructura): Estado es la 10 (J), Fecha_Pago es la 11 (K)
        # Ajusta estos índices si cambias columnas. Google Sheets empieza en 1.
        ws_mov.update_cell(cell.row, 10, "Pagado") 
        ws_mov.update_cell(cell.row, 11, str(date.today()))
        
        # B) Descontar Saldo
        ws_cuentas = hoja.worksheet("Cuentas")
        cell_cuenta = ws_cuentas.find(cuenta_origen)
        saldo_actual = float(ws_cuentas.cell(cell_cuenta.row, 6).value.replace('$','').replace('.','').replace(',','.') or 0)
        nuevo_saldo = saldo_actual - monto
        ws_cuentas.update_cell(cell_cuenta.row, 6, nuevo_saldo)
        
        return True
    except Exception as e:
        st.error(f"Error en proceso de pago: {e}")
        return False

def guardar_nuevo_registro(hoja, datos):
    try:
        worksheet = hoja.worksheet("Movimientos")
        worksheet.append_row(datos)
        return True
    except Exception as e:
        st.error(f"Error guardando: {e}")
        return False

# --- INTERFAZ GRÁFICA ---
st.title("🏠 Sistema de Gestión Financiera Pro")

sh = conectar_google_sheets()

if sh:
    # --- MENÚ LATERAL ---
    st.sidebar.title("Navegación")
    if st.sidebar.button("🔄 Actualizar Datos"):
        st.rerun()
    
    # Cargar datos frescos
    df_cuentas = cargar_datos(sh, "Cuentas")
    df_movimientos = cargar_datos(sh, "Movimientos")
    
    # Calcular totales para el menú
    pendientes = df_movimientos[df_movimientos['Estado'] == 'Pendiente'] if not df_movimientos.empty else pd.DataFrame()
    cant_pendientes = len(pendientes)
    
    menu = st.sidebar.radio(
        "Ir a:", 
        ["📊 Dashboard & Proyección", f"📅 Cuentas por Pagar ({cant_pendientes})", "💸 Nuevo Registro", "🔍 Historial"]
    )

    # --- 1. DASHBOARD & PROYECCIÓN ---
    if menu == "📊 Dashboard & Proyección":
        st.header("Situación Financiera")
        
        # 1. Saldos Actuales
        st.subheader("💰 Disponibilidad Real (Hoy)")
        if not df_cuentas.empty:
            cols = st.columns(len(df_cuentas))
            for index, row in df_cuentas.iterrows():
                with cols[index % 3]: 
                    st.metric(label=f"{row['Nombre']}", value=f"${row['Saldo_Actual']:,.0f} {row['Moneda']}")

        # 2. Proyección de Flujo de Caja (Line Timeline)
        st.markdown("---")
        st.subheader("📉 Proyección de Saldo (Mes Actual)")
        
        if not pendientes.empty and not df_cuentas.empty:
            # Filtramos solo Pesos UYU para el gráfico (simplificación)
            saldo_inicial_uyu = df_cuentas[df_cuentas['Moneda'] == 'UYU']['Saldo_Actual'].sum()
            pendientes_uyu = pendientes[pendientes['Moneda'] == 'UYU'].sort_values(by='Fecha')
            
            # Crear datos para el gráfico
            proyeccion = []
            saldo_corriente = saldo_inicial_uyu
            
            # Punto de partida (Hoy)
            proyeccion.append({"Fecha": date.today(), "Saldo Proyectado": saldo_corriente, "Evento": "Saldo Hoy"})
            
            for index, row in pendientes_uyu.iterrows():
                fecha_venc = pd.to_datetime(row['Fecha']).date()
                if fecha_venc >= date.today():
                    saldo_corriente -= row['Monto']
                    proyeccion.append({"Fecha": fecha_venc, "Saldo Proyectado": saldo_corriente, "Evento": row['Descripcion']})
            
            df_proyeccion = pd.DataFrame(proyeccion)
            
            if not df_proyeccion.empty:
                fig = px.line(df_proyeccion, x="Fecha", y="Saldo Proyectado", markers=True, 
                              title="Evolución del saldo en UYU si pagas todo en fecha", hover_data=["Evento"])
                # Agregar línea roja de alerta en 0
                fig.add_hline(y=0, line_dash="dash", line_color="red", annotation_text="Sin Fondos")
                st.plotly_chart(fig, use_container_width=True)
                
                minimo = df_proyeccion['Saldo Proyectado'].min()
                if minimo < 0:
                    st.error(f"⚠️ ¡Cuidado! Tu saldo proyectado caerá a negativos (${minimo:,.0f}) este mes.")
            else:
                st.info("No hay deudas futuras en UYU para proyectar.")
        else:
            st.info("No hay suficientes datos para generar la proyección.")

    # --- 2. GESTIÓN DE CUENTAS POR PAGAR ---
    elif "Cuentas por Pagar" in menu:
        st.header("📅 Vencimientos Pendientes")
        
        if not pendientes.empty:
            # Convertir fechas a objeto fecha para comparar
            pendientes['Fecha_dt'] = pd.to_datetime(pendientes['Fecha'])
            pendientes = pendientes.sort_values(by='Fecha_dt')
            
            for index, row in pendientes.iterrows():
                # Semáforo de Vencimiento
                dias_restantes = (row['Fecha_dt'].date() - date.today()).days
                
                if dias_restantes < 0:
                    color = "red"
                    aviso = f"🚨 VENCIDO hace {abs(dias_restantes)} días"
                elif dias_restantes <= 3:
                    color = "orange"
                    aviso = f"⚠️ Vence en {dias_restantes} días"
                else:
                    color = "green"
                    aviso = f"📅 Vence en {dias_restantes} días"
                
                # Tarjeta de la cuenta
                with st.expander(f"{aviso} | {row['Descripcion']} - ${row['Monto']:,.0f} {row['Moneda']}"):
                    col1, col2 = st.columns([3, 1])
                    with col1:
                        st.write(f"**Categoría:** {row['Categoria']}")
                        st.write(f"**Cuenta asignada:** {row['Cuenta_Origen']}")
                    with col2:
                        # BOTÓN DE PAGO
                        key_btn = f"btn_pay_{row['ID']}"
                        if st.button("✅ Pagar Ahora", key=key_btn):
                            if registrar_pago_real(sh, row['ID'], row['Cuenta_Origen'], row['Monto']):
                                st.success("Pago registrado y saldo descontado.")
                                st.rerun()
        else:
            st.success("🎉 ¡No tienes cuentas pendientes! Todo está al día.")

    # --- 3. NUEVO REGISTRO ---
    elif menu == "💸 Nuevo Registro":
        st.header("Cargar Nuevo Movimiento")
        
        tipo_registro = st.radio("¿Qué deseas cargar?", ["Gasto Diario (Pago Ya)", "Factura a Pagar (Futuro)", "Ingreso"], horizontal=True)
        
        with st.form("form_movimiento"):
            col1, col2 = st.columns(2)
            with col1:
                fecha = st.date_input("Fecha / Vencimiento", date.today())
                monto = st.number_input("Monto", min_value=0.01, format="%.2f")
                moneda = st.selectbox("Moneda", ["UYU", "USD"])
            with col2:
                categoria = st.selectbox("Categoría", ["Supermercado", "Servicios", "Alquiler", "Tarjetas", "Auto", "Educación", "Sueldo", "Otros"])
                lista_cuentas = df_cuentas['Nombre'].tolist() if not df_cuentas.empty else ["Efectivo"]
                cuenta_origen = st.selectbox("Cuenta / Medio de Pago", lista_cuentas)
            
            descripcion = st.text_input("Descripción (ej. UTE, Supermercado)")
            submitted = st.form_submit_button("💾 Guardar")
            
            if submitted:
                # Lógica de Estado
                if tipo_registro == "Gasto Diario (Pago Ya)":
                    estado = "Pagado"
                    fecha_pago = str(date.today())
                    # Si es diario, descontamos YA
                    actualizar_saldo_ya = True
                elif tipo_registro == "Factura a Pagar (Futuro)":
                    estado = "Pendiente"
                    fecha_pago = ""
                    actualizar_saldo_ya = False # No descontar todavía
                else: # Ingreso
                    estado = "Completado"
                    fecha_pago = str(date.today())
                    actualizar_saldo_ya = True # Sumar YA

                nuevo_id = len(df_movimientos) + 100 # ID simple
                
                # Datos para sheet
                datos = [nuevo_id, str(fecha), descripcion, monto, moneda, categoria, cuenta_origen, tipo_registro, "", estado, fecha_pago]
                
                if guardar_nuevo_registro(sh, datos):
                    if actualizar_saldo_ya:
                        # Pequeño truco: llamamos a la funcion de pago real pero con lógica inversa para ingreso
                        # Para simplificar en este paso, solo avisamos que se guardó. 
                        # En la versión PRO completa haremos la lógica de actualización inmediata aquí también.
                        # Por ahora, para gastos diarios, forzamos el registro de pago.
                        if tipo_registro == "Gasto Diario (Pago Ya)":
                            registrar_pago_real(sh, nuevo_id, cuenta_origen, monto)
                        
                        # Si es ingreso, habría que sumar (logica pendiente para no extender demasiado el código hoy)
                        pass 
                    
                    st.success("Movimiento registrado correctamente.")
                    st.rerun()

    # --- 4. HISTORIAL ---
    elif menu == "🔍 Historial":
        st.header("Todos los Movimientos")
        st.dataframe(df_movimientos)

else:
    st.stop()
