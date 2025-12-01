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
import time

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
    except: return False

def obtener_modelo_seguro():
    """Selecciona modelo evitando experimentales para no saturar cuota"""
    try:
        modelos = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        for m in modelos:
            if 'flash' in m and 'exp' not in m: return m
        if modelos: return modelos[0]
        return 'models/gemini-1.5-flash'
    except: return 'gemini-1.5-flash'

# --- UTILIDADES DE LIMPIEZA ---
def limpiar_numero(valor):
    if isinstance(valor, (int, float)): return float(valor)
    val_str = str(valor).strip().replace('$', '').replace('UYU', '').replace('USD', '').strip()
    val_str = val_str.replace('.', '').replace(',', '.') 
    try: return float(val_str)
    except: return 0.0

# --- LÓGICA FINANCIERA CENTRAL (CORREGIDA) ---
def actualizar_saldo(hoja, cuenta_nombre, monto, operacion="resta"):
    """
    Actualiza el saldo buscando dinámicamente la columna 'Saldo_Actual'.
    """
    try:
        ws = hoja.worksheet("Cuentas")
        cell = ws.find(cuenta_nombre)
        
        # BUSCAR LA COLUMNA CORRECTA AUTOMÁTICAMENTE
        headers = ws.row_values(1) # Leemos la fila 1
        if "Saldo_Actual" in headers:
            col_idx = headers.index("Saldo_Actual") + 1
        else:
            col_idx = 5 # Fallback a columna E si no encuentra nombre
            
        val_raw = ws.cell(cell.row, col_idx).value 
        saldo_actual = limpiar_numero(val_raw)
        
        nuevo_saldo = saldo_actual - monto if operacion == "resta" else saldo_actual + monto
        ws.update_cell(cell.row, col_idx, nuevo_saldo)
        return True
    except Exception as e: 
        st.error(f"Error actualizando saldo: {e}")
        return False

def revertir_impacto_saldo(hoja, movimiento):
    """
    Deshace el efecto matemático de un movimiento.
    """
    try:
        tipo = movimiento['Tipo']
        estado = movimiento['Estado']
        cuenta = movimiento['Cuenta_Origen']
        monto = limpiar_numero(movimiento['Monto'])
        
        if estado == "Pagado" and tipo == "Gasto":
            actualizar_saldo(hoja, cuenta, monto, "suma") # Devolver plata
            st.toast(f"💰 Reembolsados ${monto} a {cuenta}")
            
        elif estado == "Pagado" and tipo == "Ingreso":
            actualizar_saldo(hoja, cuenta, monto, "resta") # Quitar plata
            st.toast(f"💸 Retirados ${monto} de {cuenta}")
            
        return True
    except Exception as e:
        st.error(f"Error revirtiendo: {e}")
        return False

# --- GESTIÓN DE DATOS ---
def cargar_datos(hoja, pestaña):
    try:
        worksheet = hoja.worksheet(pestaña)
        data = worksheet.get_all_records()
        df = pd.DataFrame(data)
        cols_moneda = ['Saldo_Actual', 'Monto', 'Total_UYU', 'Minimo_UYU', 'Total_USD', 'Minimo_USD']
        if not df.empty:
            for col in df.columns:
                if col in cols_moneda:
                    df[col] = df[col].apply(limpiar_numero)
        return df
    except: return pd.DataFrame()

def guardar_movimiento(hoja, datos):
    hoja.worksheet("Movimientos").append_row(datos)

def borrar_fila_movimiento(hoja, id_movimiento):
    try:
        ws = hoja.worksheet("Movimientos")
        cell = ws.find(str(id_movimiento))
        ws.delete_rows(cell.row)
        return True
    except: return False

def editar_movimiento_fila(hoja, id_movimiento, nuevos_datos):
    try:
        ws = hoja.worksheet("Movimientos")
        cell = ws.find(str(id_movimiento))
        row = cell.row
        # Mapeo fijo de columnas para editar (Ajustado a tu estructura)
        # 1:ID, 2:Fecha, 3:Desc, 4:Monto, 5:Moneda, 6:Cat, 7:Origen, 8:Tipo, 9:URL, 10:Estado
        ws.update_cell(row, 2, str(nuevos_datos['Fecha']))
        ws.update_cell(row, 3, nuevos_datos['Descripcion'])
        ws.update_cell(row, 4, nuevos_datos['Monto'])
        ws.update_cell(row, 5, nuevos_datos['Moneda'])
        ws.update_cell(row, 6, nuevos_datos['Categoria'])
        ws.update_cell(row, 7, nuevos_datos['Cuenta_Origen'])
        ws.update_cell(row, 8, nuevos_datos['Tipo'])
        ws.update_cell(row, 10, nuevos_datos['Estado'])
        return True
    except: return False

# --- IA Y LECTURA ---
def extraer_texto_pdf(uploaded_file):
    try:
        pdf_reader = pypdf.PdfReader(uploaded_file)
        text = ""
        for page in pdf_reader.pages: text += page.extract_text() + "\n"
        return text
    except: return ""

def consultar_ia(prompt):
    nombre = obtener_modelo_seguro()
    model = genai.GenerativeModel(nombre)
    try:
        return model.generate_content(prompt).text
    except Exception as e:
        if "429" in str(e): return "⏳ Cuota excedida. Espera unos segundos."
        return f"Error: {e}"

def analizar_estado_cuenta(texto):
    prompt = f"Analista contable. Extrae JSON: {{'fecha_cierre':'YYYY-MM-DD', 'fecha_vencimiento':'YYYY-MM-DD', 'total_uyu':0.0, 'minimo_uyu':0.0, 'total_usd':0.0, 'minimo_usd':0.0, 'analisis':''}}. TEXTO: {texto[:25000]}"
    res = consultar_ia(prompt)
    try:
        txt = res.replace("```json", "").replace("```", "").strip()
        return json.loads(txt[txt.find("{"):txt.rfind("}")+1])
    except: return None

def guardar_memoria_ia(hoja, nombre, texto):
    try:
        hoja.worksheet("Memoria_IA").append_row([str(datetime.now()), str(date.today()), nombre, "PDF", texto[:30000]])
        return True
    except: return False

# --- INTERFAZ ---
st.title("🏠 Finanzas Personales & IA")

sh = conectar_google_sheets()
ia_activa = configurar_ia()

if 'form_data' not in st.session_state:
    st.session_state.form_data = {"cierre": date.today(), "venc": date.today(), "t_uyu": 0.0, "m_uyu": 0.0, "t_usd": 0.0, "m_usd": 0.0, "analisis": "", "full_text": "", "filename": ""}

if sh:
    if st.sidebar.button("🔄 Actualizar Datos"): 
        st.session_state.form_data = {"cierre": date.today(), "venc": date.today(), "t_uyu": 0.0, "m_uyu": 0.0, "t_usd": 0.0, "m_usd": 0.0, "analisis": "", "full_text": "", "filename": ""}
        st.rerun()
    
    df_cuentas = cargar_datos(sh, "Cuentas")
    df_mov = cargar_datos(sh, "Movimientos")
    df_tarj = cargar_datos(sh, "Tarjetas")
    df_memoria = cargar_datos(sh, "Memoria_IA")
    
    menu = st.sidebar.radio("Menú", ["📊 Dashboard", "🤖 Asistente IA", "📅 Calendario", "💳 Cargar Estado Cuenta", "💸 Nuevo Movimiento", "📝 Gestionar Movimientos"])

    # 1. DASHBOARD
    if menu == "📊 Dashboard":
        st.header("Resumen General")
        if 'Es_Tarjeta' in df_cuentas.columns:
            cuentas_dinero = df_cuentas[df_cuentas['Es_Tarjeta'] != 'Si']
        else: cuentas_dinero = df_cuentas
        
        st.subheader("💰 Disponibilidad")
        if not cuentas_dinero.empty:
            cols = st.columns(len(cuentas_dinero))
            for i, row in cuentas_dinero.iterrows():
                with cols[i % 3]: st.metric(row['Nombre'], f"${row['Saldo_Actual']:,.2f} {row['Moneda']}")
        
        st.markdown("---")
        st.subheader("📉 Próximos Vencimientos")
        pend = df_mov[df_mov['Estado'] == 'Pendiente']
        if not pend.empty: st.dataframe(pend[['Fecha','Descripcion','Monto','Moneda']].sort_values('Fecha').head(5), hide_index=True)
        else: st.success("Todo al día")

    # 2. IA
    elif menu == "🤖 Asistente IA":
        st.header("Consultor Financiero")
        # Contexto RAG limitado para velocidad
        ctx_docs = ""
        if not df_memoria.empty:
            df_memoria['Contenido_Texto'] = df_memoria['Contenido_Texto'].astype(str)
            for i, r in df_memoria.tail(2).iterrows(): ctx_docs += f"\n[DOC: {r['Nombre_Archivo']}]\n{r['Contenido_Texto'][:5000]}..."
            
        ctx = f"[CUENTAS] {df_cuentas[['Nombre','Saldo_Actual']].to_string(index=False)} \n [DOCS] {ctx_docs}"
        
        if "msgs" not in st.session_state: st.session_state.msgs = []
        for m in st.session_state.msgs:
            with st.chat_message(m["role"]): st.write(m["content"])
        if p := st.chat_input("Consulta..."):
            st.session_state.msgs.append({"role":"user","content":p})
            with st.chat_message("user"): st.write(p)
            res = consultar_ia(ctx + "\n Usuario: " + p)
            with st.chat_message("assistant"): st.write(res)
            st.session_state.msgs.append({"role":"assistant","content":res})

    # 3. CALENDARIO
    elif menu == "📅 Calendario":
        st.header("Vencimientos")
        col_cal, col_acc = st.columns([3, 1])
        with col_cal:
            evs = []
            for i, r in df_mov.iterrows():
                c = "#FF4B4B" if r['Estado']=='Pendiente' else "#28a745"
                if r['Estado']=='En Tarjeta': c="#17a2b8"
                evs.append({"title":f"${r['Monto']:,.0f} {r['Descripcion']}", "start":r['Fecha'], "color":c, "extendedProps":{"id":r['ID'], "m":r['Monto'], "e":r['Estado'], "d":r['Descripcion'], "mon":r['Moneda']}})
            cal = calendar(events=evs, options={"initialView":"dayGridMonth"})
        with col_acc:
            if cal.get("eventClick"):
                e = cal["eventClick"]["event"]["extendedProps"]
                st.write(f"**{e['d']}** | {e['mon']} {e['m']}")
                if e['e']=='Pendiente':
                    ctas = df_cuentas[df_cuentas.get('Es_Tarjeta',pd.Series(['No']*len(df_cuentas)))!='Si']
                    orig = st.selectbox("Pagar desde:", ctas['Nombre'].tolist())
                    parcial = st.checkbox("Parcial?")
                    monto = st.number_input("Monto:", value=float(e['m'])) if parcial else float(e['m'])
                    if st.button("Pagar"):
                        actualizar_saldo(sh, orig, monto, "resta")
                        ws = sh.worksheet("Movimientos")
                        cell = ws.find(str(e['id']))
                        ws.update_cell(cell.row, 10, "Pagado")
                        ws.update_cell(cell.row, 11, str(date.today()))
                        if parcial and monto < e['m']:
                             guardar_movimiento(sh, [len(df_mov)+500, str(date.today()+timedelta(days=30)), f"Saldo {e['d']}", e['m']-monto, e['mon'], "Deuda", "Tarjeta", "Factura Futura", "", "Pendiente", ""])
                        st.success("Listo"); st.rerun()

    # 4. CARGAR PDF
    elif menu == "💳 Cargar Estado Cuenta":
        st.header("Cargar PDF")
        up = st.file_uploader("PDF", type="pdf")
        if up and st.button("Analizar"):
            with st.spinner("Leyendo..."):
                txt = extraer_texto_pdf(up)
                dat = analizar_estado_cuenta(txt)
                if dat:
                    def to_d(x):
                        try: return datetime.strptime(x, "%Y-%m-%d").date()
                        except: return date.today()
                    st.session_state.form_data.update({
                        "cierre":to_d(dat.get("fecha_cierre")), 
                        "venc":to_d(dat.get("fecha_vencimiento")), 
                        "t_uyu":float(dat.get("total_uyu",0)), "t_usd":float(dat.get("total_usd",0)),
                        "full_text": txt, "filename": up.name
                    })
                    st.success("Datos leídos")
        
        with st.form("form_pdf"):
            tj = st.selectbox("Tarjeta", df_tarj['Nombre'].tolist() if not df_tarj.empty else [])
            c1, c2 = st.columns(2)
            with c1: t_uyu = st.number_input("Total UYU", value=float(st.session_state.form_data['t_uyu']))
            with c2: t_usd = st.number_input("Total USD", value=float(st.session_state.form_data['t_usd']))
            f_venc = st.date_input("Vencimiento", value=st.session_state.form_data.get('venc', date.today()))
            memoria = st.checkbox("Guardar en Memoria", value=True)
            
            if st.form_submit_button("Guardar"):
                if t_uyu > 0: guardar_movimiento(sh, [len(df_mov)+1, str(f_venc), f"Resumen {tj} UYU", t_uyu, "UYU", "Tarjeta", tj, "Factura Futura", "", "Pendiente", ""])
                if t_usd > 0: guardar_movimiento(sh, [len(df_mov)+2, str(f_venc), f"Resumen {tj} USD", t_usd, "USD", "Tarjeta", tj, "Factura Futura", "", "Pendiente", ""])
                if memoria and st.session_state.form_data["full_text"]:
                    guardar_memoria_ia(sh, st.session_state.form_data["filename"], st.session_state.form_data["full_text"])
                st.success("Guardado"); st.rerun()

    # 5. NUEVO MOVIMIENTO
    elif menu == "💸 Nuevo Movimiento":
        st.header("Registrar")
        with st.form("new"):
            desc = st.text_input("Descripción")
            c1, c2 = st.columns(2)
            with c1:
                f = st.date_input("Fecha", date.today())
                m = st.number_input("Monto", min_value=0.01)
                t = st.selectbox("Tipo", ["Gasto", "Ingreso", "Factura Futura"])
            with c2:
                mon = st.selectbox("Moneda", ["UYU", "USD"])
                cta = st.selectbox("Cuenta", df_cuentas['Nombre'].tolist() if not df_cuentas.empty else [])
            if st.form_submit_button("Guardar"):
                es_tj = False
                if 'Es_Tarjeta' in df_cuentas.columns:
                    val = df_cuentas.loc[df_cuentas['Nombre']==cta, 'Es_Tarjeta'].values
                    if len(val)>0 and val[0]=="Si": es_tj=True
                est = "Pagado"
                if t=="Factura Futura": est="Pendiente"
                elif es_tj and t=="Gasto": est="En Tarjeta"
                elif t=="Gasto": actualizar_saldo(sh, cta, m, "resta")
                elif t=="Ingreso": actualizar_saldo(sh, cta, m, "suma")
                guardar_movimiento(sh, [len(df_mov)+100, str(f), desc, m, mon, "Gral", cta, t, "", est, str(date.today()) if est=="Pagado" else ""])
                st.success("Guardado"); st.rerun()

    # 6. GESTIONAR
    elif menu == "📝 Gestionar Movimientos":
        st.header("Administrar")
        filtro = st.text_input("🔍 Buscar:")
        df_show = df_mov.copy()
        if filtro: df_show = df_show[df_show.astype(str).apply(lambda x: x.str.contains(filtro, case=False)).any(axis=1)]
        st.dataframe(df_show, use_container_width=True)
        
        ids = df_show['ID'].tolist()
        id_sel = st.selectbox("ID a modificar:", ids)
        if id_sel:
            mov = df_mov[df_mov['ID']==id_sel].iloc[0]
            c_edit, c_del = st.columns(2)
            with c_del:
                st.warning(f"Eliminar: {mov['Descripcion']} ({mov['Monto']})")
                if st.button("Eliminar Definitivamente"):
                    revertir_impacto_saldo(sh, mov)
                    borrar_fila_movimiento(sh, id_sel)
                    st.success("Eliminado"); time.sleep(1); st.rerun()
            with c_edit:
                with st.form("edit"):
                    ed_desc = st.text_input("Desc", value=mov['Descripcion'])
                    ed_monto = st.number_input("Monto", value=float(mov['Monto']))
                    ed_fecha = st.date_input("Fecha", value=pd.to_datetime(mov['Fecha']).date())
                    ed_cta = st.selectbox("Cuenta", df_cuentas['Nombre'].tolist(), index=df_cuentas['Nombre'].tolist().index(mov['Cuenta_Origen']) if mov['Cuenta_Origen'] in df_cuentas['Nombre'].tolist() else 0)
                    if st.form_submit_button("Guardar Cambios"):
                        revertir_impacto_saldo(sh, mov)
                        if mov['Estado'] == "Pagado" and mov['Tipo'] == "Gasto": actualizar_saldo(sh, ed_cta, ed_monto, "resta")
                        elif mov['Estado'] == "Pagado" and mov['Tipo'] == "Ingreso": actualizar_saldo(sh, ed_cta, ed_monto, "suma")
                        nuevos = {'Fecha':ed_fecha, 'Descripcion':ed_desc, 'Monto':ed_monto, 'Moneda':mov['Moneda'], 'Categoria':mov['Categoria'], 'Cuenta_Origen':ed_cta, 'Tipo':mov['Tipo'], 'Estado':mov['Estado']}
                        editar_movimiento_fila(sh, id_sel, nuevos)
                        st.success("Editado"); time.sleep(1); st.rerun()

else: st.stop()
