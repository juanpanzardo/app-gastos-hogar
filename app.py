import streamlit as st
import pandas as pd
from datetime import datetime, date
import gspread
from oauth2client.service_account import ServiceAccountCredentials

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

# --- FUNCIONES DE BASE DE DATOS ---
def cargar_datos(hoja, pestaña):
    try:
        worksheet = hoja.worksheet(pestaña)
        data = worksheet.get_all_records()
        df = pd.DataFrame(data)
        # Convertir montos a números si vienen como texto
        if not df.empty and 'Saldo_Actual' in df.columns:
             # Limpiar signos de moneda y comas para el cálculo
             df['Saldo_Actual'] = df['Saldo_Actual'].replace('[\$,]', '', regex=True).astype(float)
        return df
    except Exception as e:
        st.error(f"Error leyendo {pestaña}: {e}")
        return pd.DataFrame()

def actualizar_saldo(hoja, nombre_cuenta, monto, es_ingreso):
    try:
        ws_cuentas = hoja.worksheet("Cuentas")
        # Buscar la celda que tiene el nombre de la cuenta
        cell = ws_cuentas.find(nombre_cuenta)
        
        # El saldo actual está en la columna 6 (F) - Ajusta si tu Excel es distinto
        # Fila = cell.row, Columna = 6
        saldo_actual_str = ws_cuentas.cell(cell.row, 6).value
        
        # Limpiar formato de moneda ($1,000.00 -> 1000.00)
        if isinstance(saldo_actual_str, str):
            saldo_actual_str = saldo_actual_str.replace('$', '').replace('.', '').replace(',', '.')
            if saldo_actual_str == "": saldo_actual_str = "0"
            
        saldo_actual = float(saldo_actual_str)
        
        # Calcular nuevo saldo
        if es_ingreso:
            nuevo_saldo = saldo_actual + monto
        else:
            nuevo_saldo = saldo_actual - monto
            
        # Actualizar en la hoja
        ws_cuentas.update_cell(cell.row, 6, nuevo_saldo)
        return True
    except Exception as e:
        st.error(f"Error actualizando saldo: {e}")
        return False

def guardar_movimiento(hoja, datos):
    try:
        worksheet = hoja.worksheet("Movimientos")
        worksheet.append_row(datos)
        return True
    except Exception as e:
        st.error(f"Error guardando movimiento: {e}")
        return False

# --- INTERFAZ GRÁFICA ---
st.title("🏠 Sistema de Gestión Financiera")

sh = conectar_google_sheets()

if sh:
    # --- MENÚ LATERAL ---
    st.sidebar.title("Navegación")
    if st.sidebar.button("🔄 Actualizar Datos"):
        st.rerun()
    st.sidebar.markdown("---")
    menu = st.sidebar.radio("Ir a:", ["📊 Dashboard", "💸 Nuevo Movimiento", "💳 Tarjetas", "🔍 Ver Registros"])

    # Cargar datos
    df_cuentas = cargar_datos(sh, "Cuentas")
    df_tarjetas = cargar_datos(sh, "Tarjetas")
    df_movimientos = cargar_datos(sh, "Movimientos")
    
    # --- 1. DASHBOARD ---
    if menu == "📊 Dashboard":
        st.header("Estado Financiero Actual")
        st.subheader("💰 Mis Cuentas")
        if not df_cuentas.empty:
            cols = st.columns(len(df_cuentas))
            for index, row in df_cuentas.iterrows():
                with cols[index % 3]: 
                    st.metric(
                        label=f"{row['Nombre']} ({row['Moneda']})", 
                        value=f"${row['Saldo_Actual']:,.2f}"
                    )
        else:
            st.warning("No hay cuentas configuradas.")

    # --- 2. NUEVO MOVIMIENTO ---
    elif menu == "💸 Nuevo Movimiento":
        st.header("Registrar Ingreso o Gasto")
        
        with st.form("form_movimiento"):
            col1, col2 = st.columns(2)
            with col1:
                fecha = st.date_input("Fecha", date.today())
                tipo = st.selectbox("Tipo", ["Gasto", "Ingreso"])
                monto = st.number_input("Monto", min_value=0.01, format="%.2f")
            with col2:
                moneda = st.selectbox("Moneda", ["UYU", "USD"])
                categoria = st.selectbox("Categoría", ["Supermercado", "Servicios", "Auto", "Comida", "Salud", "Educación", "Sueldo", "Otros"])
                # Selector de Cuenta
                lista_cuentas = df_cuentas['Nombre'].tolist() if not df_cuentas.empty else ["Efectivo"]
                cuenta_origen = st.selectbox("Cuenta Afectada", lista_cuentas)
            
            descripcion = st.text_input("Descripción")
            submitted = st.form_submit_button("💾 Guardar y Actualizar Saldo")
            
            if submitted:
                # 1. Guardar el movimiento
                nuevo_id = len(df_movimientos) + 1
                datos_fila = [nuevo_id, str(fecha), descripcion, monto, moneda, categoria, cuenta_origen, tipo, ""]
                
                guardado_ok = guardar_movimiento(sh, datos_fila)
                
                # 2. Actualizar el saldo de la cuenta
                es_ingreso = True if tipo == "Ingreso" else False
                saldo_ok = actualizar_saldo(sh, cuenta_origen, monto, es_ingreso)
                
                if guardado_ok and saldo_ok:
                    st.success(f"✅ ¡Éxito! Gasto registrado y saldo de '{cuenta_origen}' actualizado.")
                    st.rerun()

    # --- 3. TARJETAS ---
    elif menu == "💳 Tarjetas":
        st.header("Gestión de Tarjetas")
        st.dataframe(df_tarjetas)

    # --- 4. VER REGISTROS ---
    elif menu == "🔍 Ver Registros":
        st.header("Historial de Movimientos")
        st.dataframe(df_movimientos)

else:
    st.stop()
