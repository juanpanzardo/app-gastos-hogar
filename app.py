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
        # Definir el alcance (permisos)
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        
        # Cargar credenciales desde los Secretos de Streamlit
        creds_dict = dict(st.secrets["service_account"])
        
        # Crear credenciales usando gspread
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        
        # Abrir la hoja de cálculo
        sh = client.open("Gastos_Hogar_DB")
        return sh
    except Exception as e:
        st.error(f"❌ Error al conectar con Google Sheets: {e}")
        return None

# --- FUNCIONES DE BASE DE DATOS ---
def cargar_datos(hoja, pestaña):
    try:
        worksheet = hoja.worksheet(pestaña)
        data = worksheet.get_all_records()
        return pd.DataFrame(data)
    except Exception as e:
        st.error(f"Error al leer la pestaña '{pestaña}': {e}")
        return pd.DataFrame()

def guardar_movimiento(hoja, datos):
    try:
        worksheet = hoja.worksheet("Movimientos")
        worksheet.append_row(datos)
        return True
    except Exception as e:
        st.error(f"Error al guardar: {e}")
        return False

# --- INTERFAZ GRÁFICA ---
st.title("🏠 Sistema de Gestión Financiera")

# Conectar DB
sh = conectar_google_sheets()

if sh:
    # --- MENÚ LATERAL ---
    st.sidebar.title("Navegación")
    
    # Botón para forzar actualización
    if st.sidebar.button("🔄 Actualizar Datos"):
        st.rerun()
    
    st.sidebar.markdown("---")
    
    menu = st.sidebar.radio(
        "Ir a:", 
        ["📊 Dashboard", "💸 Nuevo Movimiento", "💳 Tarjetas", "🔍 Ver Registros"]
    )

    # Cargar datos en memoria
    df_cuentas = cargar_datos(sh, "Cuentas")
    df_tarjetas = cargar_datos(sh, "Tarjetas")
    df_movimientos = cargar_datos(sh, "Movimientos")
    
    # --- 1. DASHBOARD ---
    if menu == "📊 Dashboard":
        st.header("Estado Financiero Actual")
        
        # Mostrar Cuentas (Saldos)
        st.subheader("💰 Mis Cuentas")
        if not df_cuentas.empty:
            # Filtramos solo columnas relevantes para mostrar limpio
            cols = st.columns(len(df_cuentas))
            for index, row in df_cuentas.iterrows():
                # Evitar error si hay muchas cuentas, usando módulo
                with cols[index % 3]: 
                    st.metric(
                        label=f"{row['Nombre']} ({row['Moneda']})", 
                        value=f"${row['Saldo_Actual']:,}"
                    )
        else:
            st.warning("No se encontraron cuentas. Revisa la pestaña 'Cuentas' en tu Google Sheet.")

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
                
                # Selector de Cuenta dinámico
                lista_cuentas = df_cuentas['Nombre'].tolist() if not df_cuentas.empty else ["Efectivo"]
                cuenta_origen = st.selectbox("Cuenta / Medio de Pago", lista_cuentas)
            
            descripcion = st.text_input("Descripción")
            submitted = st.form_submit_button("💾 Guardar Movimiento")
            
            if submitted:
                # ID | Fecha | Descripcion | Monto | Moneda | Categoria | Cuenta_Origen | Tipo | Comprobante_URL
                nuevo_id = len(df_movimientos) + 1
                datos_fila = [
                    nuevo_id, 
                    str(fecha), 
                    descripcion, 
                    monto, 
                    moneda, 
                    categoria, 
                    cuenta_origen, 
                    tipo, 
                    ""
                ]
                
                # Guardar
                if guardar_movimiento(sh, datos_fila):
                    st.success(f"✅ Movimiento registrado: {descripcion} - ${monto}")
                    # Pequeña pausa para que el usuario vea el mensaje antes de recargar
                    st.rerun() 

    # --- 3. TARJETAS ---
    elif menu == "💳 Tarjetas":
        st.header("Gestión de Tarjetas")
        if not df_tarjetas.empty:
            st.dataframe(df_tarjetas)
        else:
            st.info("Configura tus tarjetas en la pestaña 'Tarjetas' de Google Sheets.")

    # --- 4. VER REGISTROS ---
    elif menu == "🔍 Ver Registros":
        st.header("Historial de Movimientos")
        if not df_movimientos.empty:
            st.dataframe(df_movimientos)
        else:
            st.info("Aún no hay movimientos registrados.")

else:
    st.stop()
