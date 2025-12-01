import streamlit as st
import pandas as pd
from datetime import datetime, date, timedelta
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import plotly.express as px
from streamlit_calendar import calendar
import google.generativeai as genai
import pypdf
import json
import re

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

# --- CONFIGURACIÓN IA ROBUSTA ---
def configurar_ia():
    try:
        api_key = st.secrets["general"]["google_api_key"]
        genai.configure(api_key=api_key)
        return True
    except:
        return False

def obtener_modelo_activo():
    """Prueba modelos en orden de prioridad hasta encontrar uno que funcione"""
    modelos_a_probar = ['gemini-1.5-flash', 'gemini-1.5-pro', 'gemini-pro']
    
    # Intentamos listar lo que Google nos ofrece
    try:
        disponibles = [m.name for m in genai.list_models()]
    except:
        disponibles = []

    # 1. Si Flash está en la lista oficial, úsalo
    for m in modelos_a_probar:
        if f"models/{m}" in disponibles or m in disponibles:
            return m
            
    # 2. Si no pudimos listar, probamos a ciegas el clásico confiable
    return 'gemini-pro'

# --- FUNCIONES DE LECTURA DE PDF ---
def extraer_texto_pdf(uploaded_file):
    try:
        pdf_reader = pypdf.PdfReader(uploaded_file)
        text = ""
        for page in pdf_reader.pages:
            text += page.extract_text() + "\n"
        return text
    except Exception as e:
        return f"Error leyendo PDF: {e}"

def analizar_estado_cuenta(texto_pdf):
    """Envía el texto a la IA para extraer datos JSON"""
    nombre_modelo = obtener_modelo_activo()
    model = genai.GenerativeModel(nombre_modelo)
    
    prompt = f"""
    Eres un asistente contable. Analiza este texto de un estado de cuenta de tarjeta de crédito.
    
    TEXTO:
    {texto_pdf[:10000]} 
    
    TAREA:
    Extrae los datos en JSON.
    Si no encuentras un dato, pon 0.0 o la fecha de hoy.
    Formato fecha: YYYY-MM-DD.
    
    JSON ESPERADO:
    {{
        "fecha_cierre": "YYYY-MM-DD",
        "fecha_vencimiento": "YYYY-MM-DD",
        "total_uyu": 0.0,
        "minimo_uyu": 0.0,
        "total_usd": 0.0,
        "minimo_usd": 0.0,
        "analisis": "Resumen breve de en qué gasté más dinero."
    }}
    """
    
    try:
        response = model.generate_content(prompt)
        texto_limpio = response.text.replace("```json", "").replace("```", "").strip()
        # A veces la IA añade texto antes del JSON, buscamos la primera {
        inicio = texto_limpio.find("{")
        fin = texto_limpio.rfind("}") + 1
        json_final = texto_limpio[inicio:fin]
        
        datos = json.loads(json_final)
        return datos
    except Exception as e:
        st.error(f"Error IA ({nombre_modelo}): {e}")
        return None

# --- FUNCIONES LÓGICAS (Mantenemos las anteriores) ---
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
    except: return False

def guardar_movimiento(hoja, datos):
    hoja.worksheet("Movimientos").append_row(datos)

# --- INTERFAZ ---
st.title("🏠 Finanzas Personales & IA")

sh = conectar_google_sheets()
ia_activa = configurar_ia()

if 'form_data' not in st.session_state:
    st.session_state.form_data = {
        "cierre": date.today(),
        "venc": date.today() + timedelta(days=10),
        "t_uyu": 0.0, "m_uyu": 0.0,
        "t_usd": 0.0, "m_usd": 0.0,
        "analisis": ""
    }

if sh:
    if st.sidebar.button("🔄 Actualizar Datos"): 
        st.session_state.form_data = {"cierre": date.today(), "venc": date.today(), "t_uyu": 0.0, "m_uyu": 0.0, "t_usd": 0.0, "m_usd": 0.0, "analisis": ""}
        st.rerun()
    
    df_cuentas = cargar_datos(sh, "Cuentas")
    df_mov = cargar_datos(sh, "Movimientos")
    df_tarj = cargar_datos(sh, "Tarjetas")
    df_resum = cargar_datos(sh, "Resumenes")
    
    menu = st.sidebar.radio("Menú Principal", ["📊 Dashboard", "💳 Cargar Estado Cuenta (PDF)", "🤖 Asistente IA", "📅 Calendario de Pagos", "💸 Nuevo Gasto/Ingreso", "🔍 Ver Datos"])

    # 1. DASHBOARD
    if menu == "📊 Dashboard":
        st.header("Resumen General")
        if 'Es_Tarjeta' in df_cuentas.columns:
            cuentas_dinero = df_cuentas[df_cuentas['Es_Tarjeta'] != 'Si']
        else:
            cuentas_dinero = df_cuentas 

        st.subheader("💰 Disponibilidad")
        if not cuentas_dinero.empty:
            cols = st.columns(len(cuentas_dinero))
            for i, row in cuentas_dinero.iterrows():
                with cols[i % 3]: st.metric(row['Nombre'], f"${row['Saldo_Actual']:,.0f} {row['Moneda']}")
        
        st.markdown("---")
        st.subheader("📉 Próximos Vencimientos")
        pendientes = df_mov[df_mov['Estado'] == 'Pendiente']
        if not pendientes.empty:
            st.dataframe(pendientes[['Fecha', 'Descripcion', 'Monto', 'Moneda']].sort_values('Fecha').head(5), hide_index=True)
        else: st.success("¡Todo al día!")

    # 2. CARGAR ESTADO DE CUENTA (AUTOMÁTICO)
    elif menu == "💳 Cargar Estado Cuenta (PDF)":
        st.header("Procesar Estado de Cuenta con IA")
        st.markdown("Sube tu archivo PDF y la IA extraerá los totales y vencimientos automáticamente.")
        
        uploaded_file = st.file_uploader("Arrastra tu PDF aquí", type="pdf")
        
        if uploaded_file is not None:
            if st.button("🤖 Analizar Documento"):
                with st.spinner("Leyendo documento e interpretando datos..."):
                    texto = extraer_texto_pdf(uploaded_file)
                    # Usamos la nueva funcion robusta
                    datos_ia = analizar_estado_cuenta(texto)
                    
                    if datos_ia:
                        try:
                            # Intentamos parsear fechas, si falla usamos hoy
                            def parse_date(d_str):
                                try: return datetime.strptime(d_str, '%Y-%m-%d').date()
                                except: return date.today()

                            st.session_state.form_data["cierre"] = parse_date(datos_ia.get("fecha_cierre"))
                            st.session_state.form_data["venc"] = parse_date(datos_ia.get("fecha_vencimiento"))
                            st.session_state.form_data["t_uyu"] = float(datos_ia.get("total_uyu", 0))
                            st.session_state.form_data["m_uyu"] = float(datos_ia.get("minimo_uyu", 0))
                            st.session_state.form_data["t_usd"] = float(datos_ia.get("total_usd", 0))
                            st.session_state.form_data["m_usd"] = float(datos_ia.get("minimo_usd", 0))
                            st.session_state.form_data["analisis"] = datos_ia.get("analisis", "")
                            st.success("✅ Datos extraídos.")
                        except Exception as e:
                            st.error(f"Error procesando datos IA: {e}")
        
        st.divider()
        if st.session_state.form_data["analisis"]:
            st.info(f"📊 **Análisis:** {st.session_state.form_data['analisis']}")

        with st.form("form_estado_cuenta"):
            tarjeta = st.selectbox("Tarjeta", df_tarj['Nombre'].tolist() if not df_tarj.empty else [])
            c1, c2 = st.columns(2)
            with c1:
                f_cierre = st.date_input("Cierre", value=st.session_state.form_data["cierre"])
                total_uyu = st.number_input("Total UYU", value=st.session_state.form_data["t_uyu"])
                min_uyu = st.number_input("Mínimo UYU", value=st.session_state.form_data["m_uyu"])
            with c2:
                f_venc = st.date_input("Vencimiento", value=st.session_state.form_data["venc"])
                total_usd = st.number_input("Total USD", value=st.session_state.form_data["t_usd"])
                min_usd = st.number_input("Mínimo USD", value=st.session_state.form_data["m_usd"])
            
            if st.form_submit_button("💾 Guardar Resumen"):
                try:
                    sh.worksheet("Resumenes").append_row([len(df_resum)+1, tarjeta, str(f_cierre), str(f_venc), total_uyu, min_uyu, total_usd, min_usd, "Pendiente"])
                    if total_uyu > 0: guardar_movimiento(sh, [len(df_mov)+1, str(f_venc), f"Resumen {tarjeta} (UYU)", total_uyu, "UYU", "Tarjeta", tarjeta, "Factura Futura", "", "Pendiente", ""])
                    if total_usd > 0: guardar_movimiento(sh, [len(df_mov)+2, str(f_venc), f"Resumen {tarjeta} (USD)", total_usd, "USD", "Tarjeta", tarjeta, "Factura Futura", "", "Pendiente", ""])
                    st.success("¡Cargado!"); st.session_state.form_data["analisis"] = ""; st.rerun()
                except: st.error("Falta hoja 'Resumenes'.")

    # 3. ASISTENTE IA
    elif menu == "🤖 Asistente IA":
        st.header("Consultor Financiero")
        contexto = f"""
        Experto en finanzas. Datos:
        [CUENTAS] {df_cuentas[['Nombre', 'Saldo_Actual', 'Moneda']].to_string(index=False)}
        [PENDIENTES] {df_mov[df_mov['Estado'] == 'Pendiente'][['Fecha', 'Descripcion', 'Monto']].to_string(index=False)}
        """
        if "messages" not in st.session_state: st.session_state.messages = []
        for message in st.session_state.messages:
            with st.chat_message(message["role"]): st.markdown(message["content"])
        
        if prompt := st.chat_input("Consulta..."):
            st.session_state.messages.append({"role": "user", "content": prompt})
            with st.chat_message("user"): st.markdown(prompt)
            try:
                nombre_modelo = obtener_modelo_activo() # Usamos la función segura
                model = genai.GenerativeModel(nombre_modelo)
                response = model.generate_content(contexto + "\n\nUser: " + prompt)
                with st.chat_message("assistant"): st.markdown(response.text)
                st.session_state.messages.append({"role": "assistant", "content": response.text})
            except Exception as e: st.error(f"Error IA: {e}")

    # 4. CALENDARIO
    elif menu == "📅 Calendario de Pagos":
        st.header("Agenda de Vencimientos")
        col_cal, col_acc = st.columns([3, 1])
        with col_cal:
            eventos = []
            for i, row in df_mov.iterrows():
                color = "#FF4B4B" if row['Estado'] == 'Pendiente' else "#28a745"
                if row['Estado'] == 'En Tarjeta': color = "#17a2b8"
                eventos.append({
                    "title": f"${row['Monto']} {row['Descripcion']}", "start": row['Fecha'],
                    "backgroundColor": color, "borderColor": color,
                    "extendedProps": {"id": row['ID'], "monto": row['Monto'], "estado": row['Estado'], "desc": row['Descripcion'], "moneda": row['Moneda']}
                })
            cal = calendar(events=eventos, options={"initialView": "dayGridMonth"})
        
        with col_acc:
            if cal.get("eventClick"):
                e = cal["eventClick"]["event"]["extendedProps"]
                st.write(f"**{e['desc']}** | {e['moneda']} {e['monto']}")
                if e['estado'] == 'Pendiente':
                    cuentas_pago = df_cuentas[df_cuentas.get('Es_Tarjeta', pd.Series(['No']*len(df_cuentas))) != 'Si']
                    origen = st.selectbox("Pagar desde:", cuentas_pago['Nombre'].tolist(), key="pay_origin")
                    es_parcial = st.checkbox("¿Pago parcial?")
                    monto_a_pagar = st.number_input("A pagar:", value=float(e['monto']), key="pay_val") if es_parcial else float(e['monto'])
                    if st.button("✅ Pagar"):
                        actualizar_saldo(sh, origen, monto_a_pagar, "resta")
                        ws_mov = sh.worksheet("Movimientos")
                        cell = ws_mov.find(str(e['id']))
                        ws_mov.update_cell(cell.row, 10, "Pagado")
                        ws_mov.update_cell(cell.row, 11, str(date.today()))
                        if es_parcial and monto_a_pagar < e['monto']:
                            row_new = [len(df_mov)+500, str(date.today() + timedelta(days=30)), f"Saldo {e['desc']}", e['monto']-monto_a_pagar, e['moneda'], "Deuda", "Tarjeta", "Factura Futura", "", "Pendiente", ""]
                            guardar_movimiento(sh, row_new)
                        st.success("Pagado!"); st.rerun()

    # 5. NUEVO GASTO
    elif menu == "💸 Nuevo Gasto/Ingreso":
        st.header("Cargar Movimiento")
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
                st.success("Listo"); st.rerun()

    elif menu == "🔍 Ver Datos": st.dataframe(df_mov)

else: st.stop()
