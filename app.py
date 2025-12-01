import streamlit as st
import pandas as pd
from datetime import datetime, date, timedelta
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import plotly.express as px
from streamlit_calendar import calendar # Nueva librería mágica

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

# --- FUNCIONES DE BASE DE DATOS Y LÓGICA ---
def cargar_datos(hoja, pestaña):
    try:
        worksheet = hoja.worksheet(pestaña)
        data = worksheet.get_all_records()
        df = pd.DataFrame(data)
        if not df.empty:
            if 'Saldo_Actual' in df.columns:
                df['Saldo_Actual'] = df['Saldo_Actual'].replace('[\$,]', '', regex=True).replace('', 0).astype(float)
            if 'Monto' in df.columns:
                 df['Monto'] = df['Monto'].replace('[\$,]', '', regex=True).replace('', 0).astype(float)
        return df
    except Exception as e:
        # st.error(f"Error leyendo {pestaña}: {e}") # Silenciar error visual si está vacía
        return pd.DataFrame()

def registrar_pago_real(hoja, id_movimiento, cuenta_origen, monto):
    try:
        # A) Actualizar Movimiento
        ws_mov = hoja.worksheet("Movimientos")
        cell = ws_mov.find(str(id_movimiento))
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
        st.error(f"Error pago: {e}")
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
st.title("🏠 Sistema de Gestión Financiera")

sh = conectar_google_sheets()

if sh:
    # --- MENÚ LATERAL ---
    if st.sidebar.button("🔄 Actualizar Datos"):
        st.rerun()
    
    df_cuentas = cargar_datos(sh, "Cuentas")
    df_movimientos = cargar_datos(sh, "Movimientos")
    
    # Calcular pendientes para notificaciones
    pendientes = df_movimientos[df_movimientos['Estado'] == 'Pendiente'] if not df_movimientos.empty else pd.DataFrame()
    
    menu = st.sidebar.radio(
        "Navegación", 
        ["📅 Calendario Inteligente", "📊 Dashboard", "💸 Carga Rápida", "💳 Tarjetas", "🔍 Historial"]
    )

    # ==============================================================================
    # 1. CALENDARIO INTELIGENTE (NUEVA FUNCIÓN ESTRELLA)
    # ==============================================================================
    if menu == "📅 Calendario Inteligente":
        st.header("Agenda de Vencimientos")
        
        col_cal, col_details = st.columns([3, 1])
        
        with col_cal:
            # Preparar eventos para el calendario
            eventos_cal = []
            if not df_movimientos.empty:
                for idx, row in df_movimientos.iterrows():
                    color = "#FF4B4B" if row['Estado'] == 'Pendiente' else "#28a745" # Rojo pendiente, Verde pago
                    eventos_cal.append({
                        "title": f"${row['Monto']} - {row['Descripcion']}",
                        "start": row['Fecha'],
                        "backgroundColor": color,
                        "borderColor": color,
                        "extendedProps": {"monto": row['Monto'], "id": row['ID'], "estado": row['Estado']}
                    })

            # Configuración visual del calendario
            calendar_options = {
                "headerToolbar": {
                    "left": "today prev,next",
                    "center": "title",
                    "right": "dayGridMonth,listMonth"
                },
                "initialView": "dayGridMonth",
                "selectable": True, # Permite hacer clic en los días
            }
            
            # RENDERIZAR CALENDARIO
            state_cal = calendar(events=eventos_cal, options=calendar_options, custom_css="""
                .fc-event-title {font-weight: bold;}
                .fc-daygrid-day {cursor: pointer;}
                .fc-daygrid-day:hover {background-color: #f0f2f6;}
            """)

        # --- LÓGICA DE CLIC EN EL CALENDARIO ---
        with col_details:
            st.subheader("Acciones")
            
            # Caso A: Se hizo clic en un día vacío (o lleno) -> CREAR NUEVO
            if state_cal.get("dateClick"):
                fecha_clic = state_cal["dateClick"]["date"]
                st.info(f"🗓️ Añadir para el: **{fecha_clic}**")
                
                with st.form("form_cal_rapido"):
                    desc = st.text_input("Descripción")
                    monto = st.number_input("Monto", min_value=0.01)
                    moneda = st.selectbox("Moneda", ["UYU", "USD"])
                    cat = st.selectbox("Categoría", ["Servicios", "Super", "Tarjetas", "Otros"])
                    
                    if st.form_submit_button("➕ Guardar Gasto"):
                        # Guardar como Pendiente
                        nuevo_id = len(df_movimientos) + 500
                        datos = [nuevo_id, fecha_clic, desc, monto, moneda, cat, "Efectivo", "Factura a Pagar (Futuro)", "", "Pendiente", ""]
                        guardar_nuevo_registro(sh, datos)
                        st.success("Agendado!")
                        st.rerun()

            # Caso B: Se hizo clic en un evento existente -> DETALLE / PAGAR
            elif state_cal.get("eventClick"):
                props = state_cal["eventClick"]["event"]["extendedProps"]
                titulo = state_cal["eventClick"]["event"]["title"]
                
                st.markdown(f"### {titulo}")
                if props['estado'] == 'Pendiente':
                    st.warning("Estado: Pendiente 🔴")
                    lista_cuentas = df_cuentas['Nombre'].tolist() if not df_cuentas.empty else ["Efectivo"]
                    cuenta_pago = st.selectbox("Pagar desde:", lista_cuentas)
                    
                    if st.button("✅ Pagar Ahora"):
                        registrar_pago_real(sh, props['id'], cuenta_pago, props['monto'])
                        st.success("¡Pagado!")
                        st.rerun()
                else:
                    st.success("Estado: Pagado 🟢")

            else:
                st.info("👈 Haz clic en un día para agregar un gasto, o en un evento para ver detalles.")

    # ==============================================================================
    # 2. DASHBOARD
    # ==============================================================================
    elif menu == "📊 Dashboard":
        st.header("Resumen Financiero")
        # Saldos
        if not df_cuentas.empty:
            cols = st.columns(len(df_cuentas))
            for index, row in df_cuentas.iterrows():
                with cols[index % 3]: 
                    st.metric(label=f"{row['Nombre']}", value=f"${row['Saldo_Actual']:,.0f} {row['Moneda']}")
        
        # Proyección (Código previo optimizado)
        if not pendientes.empty:
            st.subheader("📉 Proyección del Mes")
            saldo_uyu = df_cuentas[df_cuentas['Moneda'] == 'UYU']['Saldo_Actual'].sum()
            pendientes_uyu = pendientes[pendientes['Moneda'] == 'UYU'].sort_values(by='Fecha')
            
            proyeccion = [{"Fecha": date.today(), "Saldo": saldo_uyu, "Evento": "Hoy"}]
            curr = saldo_uyu
            for i, r in pendientes_uyu.iterrows():
                if pd.to_datetime(r['Fecha']).date() >= date.today():
                    curr -= r['Monto']
                    proyeccion.append({"Fecha": r['Fecha'], "Saldo": curr, "Evento": r['Descripcion']})
            
            df_p = pd.DataFrame(proyeccion)
            fig = px.line(df_p, x="Fecha", y="Saldo", markers=True, title="Flujo de Caja Proyectado (UYU)")
            fig.add_hline(y=0, line_dash="dash", line_color="red")
            st.plotly_chart(fig, use_container_width=True)

    # ==============================================================================
    # 3. CARGA RÁPIDA (FORMULARIO ESTÁNDAR)
    # ==============================================================================
    elif menu == "💸 Carga Rápida":
        st.header("Nuevo Movimiento")
        # ... (Mantengo la lógica de carga estándar para cuando no usas el calendario)
        with st.form("form_gral"):
            c1, c2 = st.columns(2)
            with c1:
                fecha = st.date_input("Fecha", date.today())
                monto = st.number_input("Monto", min_value=0.01)
                tipo = st.selectbox("Tipo", ["Gasto Diario", "Factura Pendiente", "Ingreso"])
            with c2:
                moneda = st.selectbox("Moneda", ["UYU", "USD"])
                cta = st.selectbox("Cuenta", df_cuentas['Nombre'].tolist() if not df_cuentas.empty else ["Efectivo"])
            desc = st.text_input("Descripción")
            
            if st.form_submit_button("Guardar"):
                est = "Pagado" if tipo == "Gasto Diario" else "Pendiente"
                if tipo == "Ingreso": est = "Completado"
                
                datos = [len(df_movimientos)+1, str(fecha), desc, monto, moneda, "Gral", cta, tipo, "", est, str(date.today()) if est=="Pagado" else ""]
                
                guardar_nuevo_registro(sh, datos)
                if tipo == "Gasto Diario": registrar_pago_real(sh, len(df_movimientos)+1, cta, monto)
                st.success("Guardado")
                st.rerun()

    elif menu == "💳 Tarjetas":
        st.header("Tarjetas")
        st.dataframe(df_tarjetas)

    elif menu == "🔍 Historial":
        st.dataframe(df_movimientos)

else:
    st.stop()
