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
    if st.sidebar.button("🔄 Actualizar Datos"): st.rerun()
    
    # Cargar Dataframes
    df_cuentas = cargar_datos(sh, "Cuentas")
    df_mov = cargar_datos(sh, "Movimientos")
    df_tarj = cargar_datos(sh, "Tarjetas")
    df_resum = cargar_datos(sh, "Resumenes")
    
    menu = st.sidebar.radio("Menú Principal", 
        ["📊 Dashboard", "🤖 Asistente IA", "📅 Calendario de Pagos", "💳 Cargar Estado Cuenta", "💸 Nuevo Gasto/Ingreso", "🔍 Ver Datos"]
    )

    # 1. DASHBOARD
    if menu == "📊 Dashboard":
        st.header("Resumen General")
        
        if 'Es_Tarjeta' in df_cuentas.columns:
            cuentas_dinero = df_cuentas[df_cuentas['Es_Tarjeta'] != 'Si']
        else:
            cuentas_dinero = df_cuentas 

        st.subheader("💰 Disponibilidad (Caja y Bancos)")
        if not cuentas_dinero.empty:
            cols = st.columns(len(cuentas_dinero))
            for i, row in cuentas_dinero.iterrows():
                with cols[i % 3]:
                    st.metric(row['Nombre'], f"${row['Saldo_Actual']:,.0f} {row['Moneda']}")
        
        st.markdown("---")
        st.subheader("📉 Próximos Vencimientos")
        pendientes = df_mov[df_mov['Estado'] == 'Pendiente']
        if not pendientes.empty:
            st.dataframe(pendientes[['Fecha', 'Descripcion', 'Monto', 'Moneda']].sort_values('Fecha').head(5), hide_index=True)
        else:
            st.success("¡Todo al día!")

    # 2. ASISTENTE IA (CORREGIDO)
    elif menu == "🤖 Asistente IA":
        st.header("Consultor Financiero")
        
        if not ia_activa:
            st.error("❌ Error de API Key. Revisa los Secrets.")
        else:
            # Crear contexto resumido
            contexto = f"""
            Eres un experto en finanzas personales. Responde en base a estos datos:
            
            [CUENTAS]
            {df_cuentas[['Nombre', 'Saldo_Actual', 'Moneda']].to_string(index=False)}
            
            [DEUDAS PENDIENTES]
            {df_mov[df_mov['Estado'] == 'Pendiente'][['Fecha', 'Descripcion', 'Monto', 'Moneda']].to_string(index=False)}
            
            [ÚLTIMOS MOVIMIENTOS]
            {df_mov.tail(10)[['Fecha', 'Descripcion', 'Monto', 'Categoria']].to_string(index=False)}
            
            Responde brevemente.
            """
            
            if "messages" not in st.session_state:
                st.session_state.messages = []

            for message in st.session_state.messages:
                with st.chat_message(message["role"]):
                    st.markdown(message["content"])

            if prompt := st.chat_input("Ej: ¿Tengo deudas pendientes?"):
                st.session_state.messages.append({"role": "user", "content": prompt})
                with st.chat_message("user"):
                    st.markdown(prompt)

                try:
                    # CORRECCIÓN AQUÍ: Usamos gemini-1.5-flash
                    model = genai.GenerativeModel('gemini-1.5-flash')
                    full_prompt = contexto + "\n\nUsuario: " + prompt
                    response = model.generate_content(full_prompt)
                    
                    with st.chat_message("assistant"):
                        st.markdown(response.text)
                    st.session_state.messages.append({"role": "assistant", "content": response.text})
                except Exception as e:
                    st.error(f"Error IA: {e}")

    # 3. CALENDARIO
    elif menu == "📅 Calendario de Pagos":
        st.header("Agenda de Vencimientos")
        col_cal, col_acc = st.columns([3, 1])
        with col_cal:
            eventos = []
            for i, row in df_mov.iterrows():
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
            cal = calendar(events=eventos, options={"initialView": "dayGridMonth"})

        with col_acc:
            st.subheader("Acciones")
            if cal.get("eventClick"):
                e = cal["eventClick"]["event"]["extendedProps"]
                st.write(f"**{e['desc']}**")
                st.write(f"{e['moneda']} {e['monto']}")
                
                if e['estado'] == 'Pendiente':
                    cuentas_pago = df_cuentas[df_cuentas.get('Es_Tarjeta', pd.Series(['No']*len(df_cuentas))) != 'Si']
                    origen = st.selectbox("Pagar desde:", cuentas_pago['Nombre'].tolist(), key="pay_origin")
                    
                    es_parcial = st.checkbox("¿Pago parcial?")
                    monto_a_pagar = st.number_input("A pagar hoy:", value=float(e['monto']), key="pay_val") if es_parcial else float(e['monto'])
                    
                    if st.button("✅ Confirmar Pago"):
                        actualizar_saldo(sh, origen, monto_a_pagar, "resta")
                        ws_mov = sh.worksheet("Movimientos")
                        cell = ws_mov.find(str(e['id']))
                        ws_mov.update_cell(cell.row, 10, "Pagado")
                        ws_mov.update_cell(cell.row, 11, str(date.today()))
                        
                        if es_parcial and monto_a_pagar < e['monto']:
                            dif = e['monto'] - monto_a_pagar
                            row_new = [len(df_mov)+500, str(date.today() + timedelta(days=30)), f"Saldo {e['desc']}", dif, e['moneda'], "Deuda", "Tarjeta", "Factura Futura", "", "Pendiente", ""]
                            guardar_movimiento(sh, row_new)
                        st.success("¡Pago registrado!")
                        st.rerun()

    # 4. CARGAR RESUMEN
    elif menu == "💳 Cargar Estado Cuenta":
        st.header("Cargar Resumen Tarjeta")
        with st.form("form_estado_cuenta"):
            tarjeta = st.selectbox("Tarjeta", df_tarj['Nombre'].tolist() if not df_tarj.empty else [])
            c1, c2 = st.columns(2)
            with c1:
                f_cierre = st.date_input("Cierre")
                total_uyu = st.number_input("Total UYU", min_value=0.0)
            with c2:
                f_venc = st.date_input("Vencimiento")
                total_usd = st.number_input("Total USD", min_value=0.0)
            
            if st.form_submit_button("Cargar"):
                try:
                    sh.worksheet("Resumenes").append_row([len(df_resum)+1, tarjeta, str(f_cierre), str(f_venc), total_uyu, 0, total_usd, 0, "Pendiente"])
                    if total_uyu > 0: guardar_movimiento(sh, [len(df_mov)+1, str(f_venc), f"Resumen {tarjeta} (UYU)", total_uyu, "UYU", "Tarjeta", tarjeta, "Factura Futura", "", "Pendiente", ""])
                    if total_usd > 0: guardar_movimiento(sh, [len(df_mov)+2, str(f_venc), f"Resumen {tarjeta} (USD)", total_usd, "USD", "Tarjeta", tarjeta, "Factura Futura", "", "Pendiente", ""])
                    st.success("Cargado!")
                    st.rerun()
                except: st.error("Crea la hoja 'Resumenes'")

    # 5. NUEVO GASTO
    elif menu == "💸 Nuevo Gasto/Ingreso":
        st.header("Registrar Movimiento")
        with st.form("form_nuevo"):
            desc = st.text_input("Descripción")
            c1, c2 = st.columns(2)
            with c1:
                fecha = st.date_input("Fecha", date.today())
                monto = st.number_input("Monto", min_value=0.01)
                tipo = st.selectbox("Tipo", ["Gasto", "Ingreso", "Factura Futura"])
            with c2:
                moneda = st.selectbox("Moneda", ["UYU", "USD"])
                cta = st.selectbox("Cuenta", df_cuentas['Nombre'].tolist() if not df_cuentas.empty else ["Efectivo"])
            
            if st.form_submit_button("Guardar"):
                es_tarjeta = False
                if 'Es_Tarjeta' in df_cuentas.columns:
                    val = df_cuentas.loc[df_cuentas['Nombre'] == cta, 'Es_Tarjeta'].values
                    if len(val) > 0 and val[0] == "Si": es_tarjeta = True
                
                estado = "Pagado"
                if tipo == "Factura Futura": estado = "Pendiente"
                elif es_tarjeta and tipo == "Gasto": estado = "En Tarjeta"
                elif tipo == "Gasto": actualizar_saldo(sh, cta, monto, "resta")
                elif tipo == "Ingreso": actualizar_saldo(sh, cta, monto, "suma")

                guardar_movimiento(sh, [len(df_mov)+100, str(fecha), desc, monto, moneda, "Gral", cta, tipo, "", estado, str(date.today()) if estado=="Pagado" else ""])
                st.success("Listo")
                st.rerun()

    elif menu == "🔍 Ver Datos":
        st.dataframe(df_mov)

else:
    st.stop()
