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

# --- CONFIGURACIÓN IA DINÁMICA ---
def configurar_ia():
    try:
        api_key = st.secrets["general"]["google_api_key"]
        genai.configure(api_key=api_key)
        return True
    except:
        return False

def obtener_mejor_modelo():
    """Busca en la cuenta del usuario qué modelos reales tiene disponibles"""
    try:
        # Listamos todos los modelos que tu API Key permite ver
        modelos_disponibles = []
        for m in genai.list_models():
            if 'generateContent' in m.supported_generation_methods:
                modelos_disponibles.append(m.name)
        
        # Prioridad: Flash > Pro 1.5 > Pro 1.0
        for m in modelos_disponibles:
            if 'flash' in m: return m
        for m in modelos_disponibles:
            if '1.5-pro' in m: return m
        
        # Si no encuentra preferidos, devuelve el primero que sirva
        if modelos_disponibles:
            return modelos_disponibles[0]
            
        return 'models/gemini-1.5-flash' # Fallback final
    except Exception as e:
        # Si falla el listado, usamos el estándar actual
        return 'models/gemini-1.5-flash'

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
    nombre_modelo = obtener_mejor_modelo()
    # st.toast(f"Usando modelo: {nombre_modelo}") # Descomentar para debug
    model = genai.GenerativeModel(nombre_modelo)
    
    prompt = f"""
    Actúa como un sistema de extracción de datos (OCR financiero).
    Analiza el siguiente texto de un estado de cuenta bancario.
    
    TEXTO:
    {texto_pdf[:15000]} 
    
    INSTRUCCIONES:
    1. Busca la Fecha de Cierre y Fecha de Vencimiento.
    2. Busca los Totales a Pagar y Pagos Mínimos en Pesos (UYU) y Dólares (USD).
    3. Genera un breve análisis de gastos.
    
    FORMATO DE SALIDA (JSON PURO):
    {{
        "fecha_cierre": "YYYY-MM-DD",
        "fecha_vencimiento": "YYYY-MM-DD",
        "total_uyu": 0.0,
        "minimo_uyu": 0.0,
        "total_usd": 0.0,
        "minimo_usd": 0.0,
        "analisis": "Resumen de texto..."
    }}
    """
    
    try:
        response = model.generate_content(prompt)
        # Limpieza agresiva del JSON
        txt = response.text.replace("```json", "").replace("```", "").strip()
        idx_ini = txt.find("{")
        idx_fin = txt.rfind("}") + 1
        return json.loads(txt[idx_ini:idx_fin])
    except Exception as e:
        st.error(f"Error procesando con IA ({nombre_modelo}): {e}")
        return None

# --- FUNCIONES LÓGICAS DE NEGOCIO ---
def cargar_datos(hoja, pestaña):
    try:
        worksheet = hoja.worksheet(pestaña)
        data = worksheet.get_all_records()
        df = pd.DataFrame(data)
        cols_moneda = ['Saldo_Actual', 'Monto', 'Total_UYU', 'Minimo_UYU', 'Total_USD', 'Minimo_USD']
        if not df.empty:
            for col in df.columns:
                if col in cols_moneda:
                    # Limpieza: quitar $, comas y convertir vacíos a 0
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

# --- INTERFAZ DE USUARIO ---
st.title("🏠 Finanzas Personales & IA")

sh = conectar_google_sheets()
ia_activa = configurar_ia()

# Estado de la sesión para el formulario PDF
if 'form_data' not in st.session_state:
    st.session_state.form_data = {
        "cierre": date.today(), "venc": date.today(),
        "t_uyu": 0.0, "m_uyu": 0.0, "t_usd": 0.0, "m_usd": 0.0, "analisis": ""
    }

if sh:
    if st.sidebar.button("🔄 Actualizar Datos"): 
        st.session_state.form_data = {"cierre": date.today(), "venc": date.today(), "t_uyu": 0.0, "m_uyu": 0.0, "t_usd": 0.0, "m_usd": 0.0, "analisis": ""}
        st.rerun()
    
    # Carga de datos
    df_cuentas = cargar_datos(sh, "Cuentas")
    df_mov = cargar_datos(sh, "Movimientos")
    df_tarj = cargar_datos(sh, "Tarjetas")
    df_resum = cargar_datos(sh, "Resumenes")
    
    menu = st.sidebar.radio("Menú Principal", ["📊 Dashboard", "💳 Cargar Estado Cuenta (PDF)", "🤖 Asistente IA", "📅 Calendario de Pagos", "💸 Nuevo Gasto/Ingreso", "🔍 Ver Datos"])

    # 1. DASHBOARD
    if menu == "📊 Dashboard":
        st.header("Resumen General")
        
        # Filtro de cuentas líquidas (No tarjetas)
        if 'Es_Tarjeta' in df_cuentas.columns:
            cuentas_dinero = df_cuentas[df_cuentas['Es_Tarjeta'] != 'Si']
        else:
            cuentas_dinero = df_cuentas
            st.warning("⚠️ Crea la columna 'Es_Tarjeta' en la hoja Cuentas para diferenciar efectivo de crédito.")

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

    # 2. CARGAR ESTADO CUENTA (PDF + IA)
    elif menu == "💳 Cargar Estado Cuenta (PDF)":
        st.header("Procesar Estado de Cuenta")
        
        if not ia_activa: st.error("⚠️ Configura la API Key de Google para usar esta función.")
        
        uploaded_file = st.file_uploader("Sube el PDF de tu tarjeta", type="pdf")
        
        if uploaded_file is not None:
            if st.button("🤖 Leer con Inteligencia Artificial"):
                with st.spinner("Analizando documento..."):
                    texto = extraer_texto_pdf(uploaded_file)
                    datos = analizar_estado_cuenta(texto)
                    
                    if datos:
                        # Convertir strings a fechas/floats seguros
                        def to_date(x): 
                            try: return datetime.strptime(x, "%Y-%m-%d").date()
                            except: return date.today()
                        
                        st.session_state.form_data["cierre"] = to_date(datos.get("fecha_cierre"))
                        st.session_state.form_data["venc"] = to_date(datos.get("fecha_vencimiento"))
                        st.session_state.form_data["t_uyu"] = float(datos.get("total_uyu", 0))
                        st.session_state.form_data["m_uyu"] = float(datos.get("minimo_uyu", 0))
                        st.session_state.form_data["t_usd"] = float(datos.get("total_usd", 0))
                        st.session_state.form_data["m_usd"] = float(datos.get("minimo_usd", 0))
                        st.session_state.form_data["analisis"] = datos.get("analisis", "")
                        st.success("✅ Datos extraídos.")

        st.divider()
        if st.session_state.form_data["analisis"]:
            st.info(f"📊 **Análisis:** {st.session_state.form_data['analisis']}")

        with st.form("form_estado"):
            tarjeta = st.selectbox("Tarjeta", df_tarj['Nombre'].tolist() if not df_tarj.empty else [])
            c1, c2 = st.columns(2)
            with c1:
                f_cierre = st.date_input("Cierre", value=st.session_state.form_data["cierre"])
                t_uyu = st.number_input("Total UYU", value=st.session_state.form_data["t_uyu"])
                m_uyu = st.number_input("Mínimo UYU", value=st.session_state.form_data["m_uyu"])
            with c2:
                f_venc = st.date_input("Vencimiento", value=st.session_state.form_data["venc"])
                t_usd = st.number_input("Total USD", value=st.session_state.form_data["t_usd"])
                m_usd = st.number_input("Mínimo USD", value=st.session_state.form_data["m_usd"])
            
            if st.form_submit_button("💾 Guardar y Agendar"):
                try:
                    # Guardar Resumen
                    sh.worksheet("Resumenes").append_row([len(df_resum)+1, tarjeta, str(f_cierre), str(f_venc), t_uyu, m_uyu, t_usd, m_usd, "Pendiente"])
                    
                    # Generar pendientes en calendario
                    if t_uyu > 0:
                        guardar_movimiento(sh, [len(df_mov)+1, str(f_venc), f"Resumen {tarjeta} (UYU)", t_uyu, "UYU", "Tarjeta", tarjeta, "Factura Futura", "", "Pendiente", ""])
                    if t_usd > 0:
                        guardar_movimiento(sh, [len(df_mov)+2, str(f_venc), f"Resumen {tarjeta} (USD)", t_usd, "USD", "Tarjeta", tarjeta, "Factura Futura", "", "Pendiente", ""])
                    
                    st.success("¡Guardado correctamente!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error al guardar: {e}")

    # 3. ASISTENTE IA
    elif menu == "🤖 Asistente IA":
        st.header("Consultor Financiero")
        contexto = f"""
        [CUENTAS] {df_cuentas[['Nombre', 'Saldo_Actual', 'Moneda']].to_string(index=False)}
        [PENDIENTES] {df_mov[df_mov['Estado'] == 'Pendiente'][['Fecha', 'Descripcion', 'Monto']].to_string(index=False)}
        """
        if "msgs" not in st.session_state: st.session_state.msgs = []
        for m in st.session_state.msgs:
            with st.chat_message(m["role"]): st.markdown(m["content"])
            
        if prompt := st.chat_input("Consulta..."):
            st.session_state.msgs.append({"role": "user", "content": prompt})
            with st.chat_message("user"): st.markdown(prompt)
            try:
                # Usamos la función dinámica
                nm = obtener_mejor_modelo()
                model = genai.GenerativeModel(nm)
                res = model.generate_content(contexto + "\n\nUser: " + prompt)
                with st.chat_message("assistant"): st.markdown(res.text)
                st.session_state.msgs.append({"role": "assistant", "content": res.text})
            except Exception as e: st.error(f"Error IA: {e}")

    # 4. CALENDARIO
    elif menu == "📅 Calendario de Pagos":
        st.header("Agenda de Vencimientos")
        col_cal, col_acc = st.columns([3, 1])
        with col_cal:
            evs = []
            for i, row in df_mov.iterrows():
                color = "#FF4B4B" if row['Estado'] == 'Pendiente' else "#28a745"
                if row['Estado'] == 'En Tarjeta': color = "#17a2b8"
                evs.append({"title": f"${row['Monto']} {row['Descripcion']}", "start": row['Fecha'], "backgroundColor": color, "borderColor": color, "extendedProps": {"id": row['ID'], "monto": row['Monto'], "estado": row['Estado'], "desc": row['Descripcion'], "moneda": row['Moneda']}})
            cal = calendar(events=evs, options={"initialView": "dayGridMonth"})
        
        with col_acc:
            if cal.get("eventClick"):
                e = cal["eventClick"]["event"]["extendedProps"]
                st.write(f"**{e['desc']}** | {e['moneda']} {e['monto']}")
                if e['estado'] == 'Pendiente':
                    # Filtrar origen (no tarjetas)
                    cuentas_pago = df_cuentas[df_cuentas.get('Es_Tarjeta', pd.Series(['No']*len(df_cuentas))) != 'Si']
                    orig = st.selectbox("Pagar desde:", cuentas_pago['Nombre'].tolist(), key="pay_origin")
                    es_parcial = st.checkbox("¿Pago parcial?")
                    monto_a_pagar = st.number_input("Monto:", value=float(e['monto']), key="pay_val") if es_parcial else float(e['monto'])
                    
                    if st.button("✅ Pagar"):
                        actualizar_saldo(sh, orig, monto_a_pagar, "resta")
                        ws = sh.worksheet("Movimientos")
                        cell = ws.find(str(e['id']))
                        ws.update_cell(cell.row, 10, "Pagado")
                        ws.update_cell(cell.row, 11, str(date.today()))
                        if es_parcial and monto_a_pagar < e['monto']:
                             # Generar deuda remanente
                             row_new = [len(df_mov)+500, str(date.today()+timedelta(days=30)), f"Saldo {e['desc']}", e['monto']-monto_a_pagar, e['moneda'], "Deuda", "Tarjeta", "Factura Futura", "", "Pendiente", ""]
                             guardar_movimiento(sh, row_new)
                        st.success("Listo!"); st.rerun()

    # 5. NUEVO GASTO
    elif menu == "💸 Nuevo Gasto/Ingreso":
        st.header("Cargar Movimiento")
        with st.form("new_mov"):
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
                es_tj = False
                if 'Es_Tarjeta' in df_cuentas.columns:
                    val = df_cuentas.loc[df_cuentas['Nombre'] == cta, 'Es_Tarjeta'].values
                    if len(val) > 0 and val[0] == "Si": es_tj = True
                
                est = "Pagado"
                if tipo == "Factura Futura": est = "Pendiente"
                elif es_tj and tipo == "Gasto": est = "En Tarjeta"
                elif tipo == "Gasto": actualizar_saldo(sh, cta, monto, "resta")
                elif tipo == "Ingreso": actualizar_saldo(sh, cta, monto, "suma")

                guardar_movimiento(sh, [len(df_mov)+100, str(fecha), desc, monto, moneda, "Gral", cta, tipo, "", est, str(date.today()) if est=="Pagado" else ""])
                st.success("Guardado"); st.rerun()

    elif menu == "🔍 Ver Datos": st.dataframe(df_mov)

else: st.stop()
