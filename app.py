import streamlit as st
import pandas as pd
from datetime import datetime, date, timedelta
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import plotly.express as px
from streamlit_calendar import calendar
import google.generativeai as genai

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

# --- CONFIGURACIÓN IA ---
def configurar_ia():
    try:
        # Intenta obtener la clave de secrets, si falla avisa
        api_key = st.secrets["general"]["google_api_key"]
        genai.configure(api_key=api_key)
        return True
    except:
        return False

# --- FUNCIONES LÓGICAS ---
def cargar_datos(hoja, pestaña):
    try:
        worksheet = hoja.worksheet(pestaña)
        data = worksheet.get_all_records()
        df = pd.DataFrame(data)
        # Limpieza numérica robusta
        cols_moneda = ['Saldo_Actual', 'Monto', 'Total_UYU', 'Minimo_UYU', 'Total_USD', 'Minimo_USD']
        if not df.empty:
            for col in df.columns:
                if col in cols_moneda:
                    df[col] = df[col].astype(str).replace(r'[$,]', '', regex=True).replace('', '0')
                    df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
        return df
    except:
        return pd.DataFrame()

def actualizar_saldo(hoja, cuenta_nombre, monto, operacion="resta"):
    try:
        ws = hoja.worksheet("Cuentas")
        cell = ws.find(cuenta_nombre)
        # Asumimos saldo en col 6 (F), ajusta si cambiaste columnas
        val_str = str(ws.cell(cell.row, 6).value).replace('$','').replace('.','').replace(',','.')
        saldo_actual = float(val_str) if val_str else 0.0
        
        nuevo_saldo = saldo_actual - monto if operacion == "resta" else saldo_actual + monto
        ws.update_cell(cell.row, 6, nuevo_saldo)
        return True
    except Exception as e:
        st.error(f"Error actualizando saldo: {e}")
        return False

def guardar_movimiento(hoja, datos):
    hoja.worksheet("Movimientos").append_row(datos)

# --- INTERFAZ ---
st.title("🏠 Finanzas Personales & IA")

sh = conectar_google_sheets()
ia_activa = configurar_ia()

if sh:
    # Barra lateral de actualización
    if st.sidebar.button("🔄 Actualizar Datos"): st.rerun()
    
    # Cargar Dataframes
    df_cuentas = cargar_datos(sh, "Cuentas")
    df_mov = cargar_datos(sh, "Movimientos")
    df_tarj = cargar_datos(sh, "Tarjetas")
    df_resum = cargar_datos(sh, "Resumenes") # Nueva pestaña
    
    # 2) ORDENAR MENÚ: Dashboard primero
    menu = st.sidebar.radio("Menú Principal", 
        ["📊 Dashboard", "🤖 Asistente IA", "📅 Calendario de Pagos", "💳 Cargar Estado Cuenta", "💸 Nuevo Gasto/Ingreso", "🔍 Ver Datos"]
    )

    # ==============================================================================
    # 1. DASHBOARD
    # ==============================================================================
    if menu == "📊 Dashboard":
        st.header("Resumen General")
        
        # Filtrar solo cuentas de dinero real (No Tarjetas)
        if 'Es_Tarjeta' in df_cuentas.columns:
            cuentas_dinero = df_cuentas[df_cuentas['Es_Tarjeta'] != 'Si']
        else:
            cuentas_dinero = df_cuentas # Si no creaste la columna aún, muestra todo
            st.warning("⚠️ Recuerda crear la columna 'Es_Tarjeta' en la hoja Cuentas.")

        st.subheader("💰 Disponibilidad (Caja y Bancos)")
        if not cuentas_dinero.empty:
            cols = st.columns(len(cuentas_dinero))
            for i, row in cuentas_dinero.iterrows():
                with cols[i % 3]:
                    st.metric(row['Nombre'], f"${row['Saldo_Actual']:,.0f} {row['Moneda']}")
        
        # Proyección Simple
        st.markdown("---")
        st.subheader("📉 Próximos Vencimientos")
        pendientes = df_mov[df_mov['Estado'] == 'Pendiente']
        if not pendientes.empty:
            st.dataframe(pendientes[['Fecha', 'Descripcion', 'Monto', 'Moneda']].sort_values('Fecha').head(5), hide_index=True)
        else:
            st.success("¡Todo al día!")

    # ==============================================================================
    # 2. ASISTENTE IA (RECUPERADO)
    # ==============================================================================
    elif menu == "🤖 Asistente IA":
        st.header("Consultor Financiero")
        
        if not ia_activa:
            st.error("❌ No detecto la API Key de Google. Ve a 'Secrets' y configura [general] google_api_key.")
            st.info("Consigue tu clave gratis en aistudio.google.com")
        else:
            # Preparar el "Cerebro" con tus datos
            contexto = f"""
            Eres un experto en finanzas personales. Analiza mis datos actuales:
            
            [MIS CUENTAS Y SALDOS]
            {df_cuentas.to_string(index=False)}
            
            [MIS TARJETAS]
            {df_tarj.to_string(index=False)}
            
            [MOVIMIENTOS RECIENTES]
            {df_mov.tail(20).to_string(index=False)}
            
            [LO QUE DEBO (PENDIENTES)]
            {df_mov[df_mov['Estado'] == 'Pendiente'].to_string(index=False)}
            
            Responde de forma útil, breve y empática. Si pregunto si puedo comprar algo, verifica mi saldo.
            """
            
            # Historial del chat en la sesión
            if "messages" not in st.session_state:
                st.session_state.messages = []

            for message in st.session_state.messages:
                with st.chat_message(message["role"]):
                    st.markdown(message["content"])

            if prompt := st.chat_input("Ej: ¿Cuánto gasté en Supermercado este mes?"):
                st.session_state.messages.append({"role": "user", "content": prompt})
                with st.chat_message("user"):
                    st.markdown(prompt)

                try:
                    model = genai.GenerativeModel('gemini-pro')
                    full_prompt = contexto + "\n\nPregunta Usuario: " + prompt
                    response = model.generate_content(full_prompt)
                    
                    with st.chat_message("assistant"):
                        st.markdown(response.text)
                    st.session_state.messages.append({"role": "assistant", "content": response.text})
                except Exception as e:
                    st.error(f"Error de IA: {e}")

    # ==============================================================================
    # 3. CALENDARIO DE PAGOS
    # ==============================================================================
    elif menu == "📅 Calendario de Pagos":
        st.header("Agenda de Vencimientos")
        
        col_cal, col_acc = st.columns([3, 1])
        
        with col_cal:
            eventos = []
            for i, row in df_mov.iterrows():
                # Colores: Rojo (Pendiente), Verde (Pagado), Azul (Tarjeta/Informativo)
                color = "#FF4B4B"
                if row['Estado'] == 'Pagado': color = "#28a745"
                if row['Estado'] == 'En Tarjeta': color = "#17a2b8" 
                
                eventos.append({
                    "title": f"${row['Monto']} {row['Descripcion']}",
                    "start": row['Fecha'],
                    "backgroundColor": color,
                    "borderColor": color,
                    "extendedProps": {"id": row['ID'], "monto": row['Monto'], "estado": row['Estado'], "desc": row['Descripcion'], "moneda": row['Moneda']}
                })
            
            cal = calendar(events=eventos, options={"initialView": "dayGridMonth", "headerToolbar": {"left": "prev,next", "center": "title", "right": "dayGridMonth,listMonth"}})

        with col_acc:
            st.subheader("Acciones")
            if cal.get("eventClick"):
                e = cal["eventClick"]["event"]["extendedProps"]
                st.write(f"**{e['desc']}**")
                st.write(f"Importe: {e['moneda']} {e['monto']}")
                st.write(f"Estado: {e['estado']}")
                
                if e['estado'] == 'Pendiente':
                    st.markdown("---")
                    st.write("¿Realizar Pago?")
                    
                    # Filtramos cuentas origen (solo bancos/efectivo)
                    cuentas_pago = df_cuentas
                    if 'Es_Tarjeta' in df_cuentas.columns:
                        cuentas_pago = df_cuentas[df_cuentas['Es_Tarjeta'] != 'Si']
                    
                    origen = st.selectbox("Pagar desde:", cuentas_pago['Nombre'].tolist(), key="pay_origin")
                    
                    # Opción de pago parcial (para tarjetas)
                    es_parcial = st.checkbox("¿Pago parcial/mínimo?")
                    monto_a_pagar = e['monto']
                    
                    if es_parcial:
                        monto_a_pagar = st.number_input("Monto a pagar hoy:", value=float(e['monto']), key="pay_amount")
                    
                    if st.button("✅ Confirmar Pago"):
                        # 1. Descontar dinero
                        actualizar_saldo(sh, origen, monto_a_pagar, "resta")
                        
                        # 2. Marcar original como pagado
                        ws_mov = sh.worksheet("Movimientos")
                        cell = ws_mov.find(str(e['id']))
                        # Ajusta columnas segun tu hoja (J=10 Estado, K=11 Fecha Pago)
                        ws_mov.update_cell(cell.row, 10, "Pagado")
                        ws_mov.update_cell(cell.row, 11, str(date.today()))
                        
                        # 3. Si fue parcial, crear deuda nueva
                        if es_parcial and monto_a_pagar < e['monto']:
                            diferencia = e['monto'] - monto_a_pagar
                            nueva_fecha = str(date.today() + timedelta(days=30))
                            desc_nueva = f"Saldo Restante {e['desc']}"
                            # ID | Fecha | Desc | Monto | Mon | Cat | Origen | Tipo | URL | Estado | FPago
                            row_new = [len(df_mov)+500, nueva_fecha, desc_nueva, diferencia, e['moneda'], "Deuda", "Tarjeta", "Factura a Pagar (Futuro)", "", "Pendiente", ""]
                            guardar_movimiento(sh, row_new)
                            st.info(f"Se generó una deuda de {diferencia} para el mes que viene.")
                        
                        st.success("¡Pago registrado!")
                        st.rerun()

    # ==============================================================================
    # 4. CARGAR ESTADO DE CUENTA (NUEVO)
    # ==============================================================================
    elif menu == "💳 Cargar Estado Cuenta":
        st.header("Procesar Cierre de Tarjeta")
        st.info("Carga aquí los datos de tu estado de cuenta. Esto creará los avisos de vencimiento automáticamente.")
        
        tarjetas_list = df_tarj['Nombre'].tolist() if not df_tarj.empty else []
        
        with st.form("form_estado_cuenta"):
            tarjeta = st.selectbox("Selecciona Tarjeta", tarjetas_list)
            c1, c2 = st.columns(2)
            with c1:
                f_cierre = st.date_input("Fecha de Cierre")
                total_uyu = st.number_input("Total Pesos ($)", min_value=0.0)
                min_uyu = st.number_input("Mínimo Pesos ($)", min_value=0.0)
            with c2:
                f_venc = st.date_input("Fecha de Vencimiento")
                total_usd = st.number_input("Total Dólares (U$S)", min_value=0.0)
                min_usd = st.number_input("Mínimo Dólares (U$S)", min_value=0.0)
            
            if st.form_submit_button("📥 Cargar Resumen"):
                # 1. Guardar en Hoja Resumenes (para historial)
                # ID | Tarjeta | Cierre | Venc | TotUYU | MinUYU | TotUSD | MinUSD | Estado
                try:
                    sh.worksheet("Resumenes") # Verificar que existe
                    row_res = [len(df_resum)+1, tarjeta, str(f_cierre), str(f_venc), total_uyu, min_uyu, total_usd, min_usd, "Pendiente"]
                    sh.worksheet("Resumenes").append_row(row_res)
                    
                    # 2. Crear Movimientos Pendientes en Calendario (Uno por moneda)
                    if total_uyu > 0:
                        # Nota: En descripcion ponemos 'Resumen' para identificarlo facil
                        row_mov_uyu = [len(df_mov)+1, str(f_venc), f"Resumen {tarjeta} (UYU)", total_uyu, "UYU", "Tarjeta", tarjeta, "Factura a Pagar (Futuro)", "", "Pendiente", ""]
                        guardar_movimiento(sh, row_mov_uyu)
                    
                    if total_usd > 0:
                        row_mov_usd = [len(df_mov)+2, str(f_venc), f"Resumen {tarjeta} (USD)", total_usd, "USD", "Tarjeta", tarjeta, "Factura a Pagar (Futuro)", "", "Pendiente", ""]
                        guardar_movimiento(sh, row_mov_usd)
                        
                    st.success("✅ Resumen cargado. Ve al Calendario para ver los vencimientos.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error: No encontré la pestaña 'Resumenes'. Créala en Google Sheets. Detalle: {e}")

    # ==============================================================================
    # 5. NUEVO GASTO / INGRESO
    # ==============================================================================
    elif menu == "💸 Nuevo Gasto/Ingreso":
        st.header("Registrar Movimiento")
        
        with st.form("form_nuevo"):
            desc = st.text_input("Descripción (ej. Supermercado, UTE)")
            colA, colB = st.columns(2)
            with colA:
                fecha = st.date_input("Fecha", date.today())
                monto = st.number_input("Monto", min_value=0.01)
                tipo = st.selectbox("Tipo", ["Gasto", "Ingreso", "Factura Futura (Aendar)"])
            with colB:
                moneda = st.selectbox("Moneda", ["UYU", "USD"])
                categoria = st.selectbox("Categoría", ["Alimentos", "Transporte", "Servicios", "Hogar", "Ocio", "Salud", "Ropa", "Otros"])
                # Selector inteligente de cuentas
                cta_origen = st.selectbox("Medio de Pago / Cuenta", df_cuentas['Nombre'].tolist() if not df_cuentas.empty else ["Efectivo"])
            
            if st.form_submit_button("💾 Guardar"):
                # 3) LÓGICA DE TARJETAS (NO DESCONTAR)
                es_tarjeta = False
                if 'Es_Tarjeta' in df_cuentas.columns:
                    val = df_cuentas.loc[df_cuentas['Nombre'] == cta_origen, 'Es_Tarjeta'].values
                    if len(val) > 0 and val[0] == "Si":
                        es_tarjeta = True
                
                estado = "Pagado"
                fecha_pago = str(date.today())
                
                # Definir lógica según tipo
                if tipo == "Factura Futura (Aendar)":
                    estado = "Pendiente"
                    fecha_pago = ""
                    st.info("Agendado como pendiente. No se descuenta saldo aún.")
                    
                elif es_tarjeta and tipo == "Gasto":
                    estado = "En Tarjeta"
                    fecha_pago = "" # Se paga cuando venza el resumen
                    st.info("Gasto con Tarjeta registrado. Se sumará al próximo cierre. NO se descuenta saldo hoy.")
                    
                elif tipo == "Gasto":
                    # Gasto normal (Efectivo/Debito) -> Descontar YA
                    actualizar_saldo(sh, cta_origen, monto, "resta")
                    st.success(f"Descontado {monto} de {cta_origen}")
                    
                elif tipo == "Ingreso":
                    actualizar_saldo(sh, cta_origen, monto, "suma")
                    st.success(f"Ingresado {monto} a {cta_origen}")

                # Guardar en Sheet
                nuevo_id = len(df_mov) + 100
                row_data = [nuevo_id, str(fecha), desc, monto, moneda, categoria, cta_origen, tipo, "", estado, fecha_pago]
                guardar_movimiento(sh, row_data)
                
                st.success("Movimiento registrado correctamente.")
                st.rerun()

    elif menu == "🔍 Ver Datos":
        st.dataframe(df_mov)

else:
    st.stop()
