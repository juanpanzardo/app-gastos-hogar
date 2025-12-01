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
    try:
        modelos = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        for m in modelos:
            if 'flash' in m and 'exp' not in m: return m
        if modelos: return modelos[0]
        return 'models/gemini-1.5-flash'
    except: return 'gemini-1.5-flash'

# --- UTILIDADES ---
def limpiar_numero(valor):
    if isinstance(valor, (int, float)): return float(valor)
    val_str = str(valor).strip().replace('$', '').replace('UYU', '').replace('USD', '').strip()
    val_str = val_str.replace('.', '').replace(',', '.') 
    try: return float(val_str)
    except: return 0.0

# --- LÓGICA FINANCIERA CENTRAL ---
def actualizar_saldo(hoja, cuenta_nombre, monto, operacion="resta"):
    """
    operacion: 'resta' (gastar), 'suma' (ingresar/devolver)
    """
    try:
        ws = hoja.worksheet("Cuentas")
        cell = ws.find(cuenta_nombre)
        val_raw = ws.cell(cell.row, 6).value # Asumiendo Saldo en Col 6
        saldo_actual = limpiar_numero(val_raw)
        
        nuevo_saldo = saldo_actual - monto if operacion == "resta" else saldo_actual + monto
        ws.update_cell(cell.row, 6, nuevo_saldo)
        return True
    except: return False

def revertir_impacto_saldo(hoja, movimiento):
    """
    Deshace el efecto matemático de un movimiento en el saldo.
    """
    try:
        tipo = movimiento['Tipo']
        estado = movimiento['Estado']
        cuenta = movimiento['Cuenta_Origen']
        monto = limpiar_numero(movimiento['Monto'])
        
        # Solo revertimos si afectó el saldo real (Pagado/Ingresado)
        # Si estaba 'Pendiente' o 'En Tarjeta', no tocó el saldo, así que no hacemos nada.
        if estado == "Pagado" and tipo == "Gasto":
            # Si era gasto pagado, devolvemos la plata (suma)
            actualizar_saldo(hoja, cuenta, monto, "suma")
            st.toast(f"💰 Se devolvieron ${monto} a {cuenta}")
            
        elif estado == "Pagado" and tipo == "Ingreso":
            # Si era ingreso, se lo quitamos (resta)
            actualizar_saldo(hoja, cuenta, monto, "resta")
            st.toast(f"💸 Se descontaron ${monto} de {cuenta}")
            
        return True
    except Exception as e:
        st.error(f"Error revirtiendo saldo: {e}")
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

def editar_movimiento_fila(hoja, id_movimiento, nuevos_datos_dict):
    """
    Sobreescribe una fila existente.
    nuevos_datos_dict: {'Fecha':..., 'Descripcion':...}
    """
    try:
        ws = hoja.worksheet("Movimientos")
        cell = ws.find(str(id_movimiento))
        row = cell.row
        
        # Mapeo de columnas (Ajustar según tu Excel)
        # ID=1, Fecha=2, Desc=3, Monto=4, Mon=5, Cat=6, Origen=7, Tipo=8, URL=9, Estado=10, FPago=11
        ws.update_cell(row, 2, str(nuevos_datos_dict['Fecha']))
        ws.update_cell(row, 3, nuevos_datos_dict['Descripcion'])
        ws.update_cell(row, 4, nuevos_datos_dict['Monto'])
        ws.update_cell(row, 5, nuevos_datos_dict['Moneda'])
        ws.update_cell(row, 6, nuevos_datos_dict['Categoria'])
        ws.update_cell(row, 7, nuevos_datos_dict['Cuenta_Origen'])
        ws.update_cell(row, 8, nuevos_datos_dict['Tipo'])
        # Estado y F.Pago dependen de la lógica, aquí asumimos que el usuario los define o se mantienen
        ws.update_cell(row, 10, nuevos_datos_dict['Estado'])
        return True
    except Exception as e:
        st.error(f"Error editando: {e}")
        return False

# --- IA LECTURA ---
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
        if "429" in str(e): return "⏳ Cuota excedida. Espera un momento."
        return f"Error: {e}"

def analizar_estado_cuenta(texto):
    prompt = f"Analista contable. Extrae JSON: {{'fecha_cierre':'YYYY-MM-DD', 'fecha_vencimiento':'YYYY-MM-DD', 'total_uyu':0.0, 'minimo_uyu':0.0, 'total_usd':0.0, 'minimo_usd':0.0, 'analisis':''}}. TEXTO: {texto[:25000]}"
    res = consultar_ia(prompt)
    try:
        txt = res.replace("```json", "").replace("```", "").strip()
        return json.loads(txt[txt.find("{"):txt.rfind("}")+1])
    except: return None

# --- INTERFAZ ---
st.title("🏠 Finanzas Personales & IA")

sh = conectar_google_sheets()
ia_activa = configurar_ia()

if 'form_data' not in st.session_state:
    st.session_state.form_data = {"cierre": date.today(), "venc": date.today(), "t_uyu": 0.0, "m_uyu": 0.0, "t_usd": 0.0, "m_usd": 0.0, "analisis": "", "full_text": "", "filename": ""}

if sh:
    if st.sidebar.button("🔄 Actualizar Datos"): st.rerun()
    
    df_cuentas = cargar_datos(sh, "Cuentas")
    df_mov = cargar_datos(sh, "Movimientos")
    df_tarj = cargar_datos(sh, "Tarjetas")
    
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
        ctx = f"[CUENTAS] {df_cuentas[['Nombre','Saldo_Actual']].to_string(index=False)} \n [PENDIENTES] {df_mov[df_mov['Estado']=='Pendiente'][['Fecha','Descripcion','Monto']].to_string(index=False)}"
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
                    st.session_state.form_data.update({"cierre":dat.get("fecha_cierre"), "venc":dat.get("fecha_vencimiento"), "t_uyu":dat.get("total_uyu",0), "t_usd":dat.get("total_usd",0)})
                    st.success("Datos leídos")
        
        with st.form("form_pdf"):
            tj = st.selectbox("Tarjeta", df_tarj['Nombre'].tolist() if not df_tarj.empty else [])
            c1, c2 = st.columns(2)
            with c1:
                t_uyu = st.number_input("Total UYU", value=float(st.session_state.form_data['t_uyu']))
            with c2:
                t_usd = st.number_input("Total USD", value=float(st.session_state.form_data['t_usd']))
            f_venc = st.date_input("Vencimiento", value=pd.to_datetime(st.session_state.form_data['venc']).date())
            
            if st.form_submit_button("Guardar"):
                if t_uyu > 0: guardar_movimiento(sh, [len(df_mov)+1, str(f_venc), f"Resumen {tj} UYU", t_uyu, "UYU", "Tarjeta", tj, "Factura Futura", "", "Pendiente", ""])
                if t_usd > 0: guardar_movimiento(sh, [len(df_mov)+2, str(f_venc), f"Resumen {tj} USD", t_usd, "USD", "Tarjeta", tj, "Factura Futura", "", "Pendiente", ""])
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

    # ==============================================================================
    # 6. GESTIONAR MOVIMIENTOS (NUEVA FUNCIONALIDAD)
    # ==============================================================================
    elif menu == "📝 Gestionar Movimientos":
        st.header("Administrar Registros")
        st.info("⚠️ Aquí puedes eliminar o corregir errores. Si borras un gasto pagado, el dinero volverá a tu cuenta automáticamente.")
        
        # Filtros básicos para encontrar fácil
        filtro = st.text_input("🔍 Buscar por descripción o monto:")
        
        df_display = df_mov.copy()
        if filtro:
            df_display = df_display[df_display.astype(str).apply(lambda x: x.str.contains(filtro, case=False)).any(axis=1)]
        
        # Mostramos tabla interactiva simple
        st.dataframe(df_display, use_container_width=True)
        
        st.divider()
        st.subheader("🛠️ Acciones")
        
        # Selector de ID para operar
        lista_ids = df_display['ID'].tolist()
        id_selec = st.selectbox("Selecciona el ID del movimiento a modificar/eliminar:", lista_ids)
        
        if id_selec:
            # Recuperamos los datos de ese movimiento
            mov_data = df_mov[df_mov['ID'] == id_selec].iloc[0]
            
            col_edit, col_del = st.columns(2)
            
            # --- SECCIÓN ELIMINAR ---
            with col_del:
                st.markdown("### 🗑️ Eliminar")
                st.warning(f"Vas a eliminar: **{mov_data['Descripcion']}** (${mov_data['Monto']})")
                if st.button("Confirmar Eliminación", type="primary"):
                    with st.spinner("Eliminando y ajustando saldos..."):
                        # 1. Revertir saldo (Devolver plata si era gasto, quitar si era ingreso)
                        revertir_impacto_saldo(sh, mov_data)
                        # 2. Borrar fila de Excel
                        borrar_fila_movimiento(sh, id_selec)
                        st.success("Movimiento eliminado y saldos ajustados.")
                        time.sleep(1)
                        st.rerun()

            # --- SECCIÓN EDITAR ---
            with col_edit:
                st.markdown("### ✏️ Editar")
                with st.expander("Abrir formulario de edición"):
                    with st.form("form_editar"):
                        e_desc = st.text_input("Descripción", value=mov_data['Descripcion'])
                        e_monto = st.number_input("Monto", value=float(mov_data['Monto']))
                        e_fecha = st.date_input("Fecha", value=pd.to_datetime(mov_data['Fecha']).date())
                        e_cta = st.selectbox("Cuenta", df_cuentas['Nombre'].tolist(), index=df_cuentas['Nombre'].tolist().index(mov_data['Cuenta_Origen']) if mov_data['Cuenta_Origen'] in df_cuentas['Nombre'].tolist() else 0)
                        
                        if st.form_submit_button("Guardar Cambios"):
                            # Lógica de edición segura:
                            # 1. Revertimos el movimiento viejo (como si lo borráramos)
                            revertir_impacto_saldo(sh, mov_data)
                            
                            # 2. Preparamos el nuevo movimiento
                            # Determinar si el NUEVO movimiento afecta saldo
                            # (Simplificación: Asumimos que mantenemos el Tipo y Estado originales pero con nuevos valores)
                            # Si cambiamos de cuenta, la reversión afectó a la vieja, y ahora afectaremos a la nueva.
                            
                            nuevo_tipo = mov_data['Tipo']
                            nuevo_estado = mov_data['Estado']
                            
                            # Si es Gasto Pagado, descontamos el NUEVO monto de la NUEVA cuenta
                            if nuevo_estado == "Pagado" and nuevo_tipo == "Gasto":
                                actualizar_saldo(sh, e_cta, e_monto, "resta")
                            elif nuevo_estado == "Pagado" and nuevo_tipo == "Ingreso":
                                actualizar_saldo(sh, e_cta, e_monto, "suma")
                            
                            # 3. Actualizamos la fila en Excel
                            nuevos_datos = {
                                'Fecha': e_fecha, 'Descripcion': e_desc, 'Monto': e_monto,
                                'Moneda': mov_data['Moneda'], 'Categoria': mov_data['Categoria'],
                                'Cuenta_Origen': e_cta, 'Tipo': nuevo_tipo, 'Estado': nuevo_estado
                            }
                            editar_movimiento_fila(sh, id_selec, nuevos_datos)
                            
                            st.success("Movimiento actualizado y saldos recalculados.")
                            time.sleep(1)
                            st.rerun()

else: st.stop()
