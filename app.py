import streamlit as st
from datetime import datetime
import pandas as pd

# Configuración de la página (Debe ser lo primero)
st.set_page_config(
    page_title="Gastos del Hogar AI",
    page_icon="🏠",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Título Principal
st.title("🏠 Control de Gastos del Hogar")

# Menú Lateral
st.sidebar.header("Menú Principal")
opcion = st.sidebar.radio(
    "Ir a:",
    ["📊 Tablero Principal", "💸 Ingresar Gasto/Ingreso", "💳 Tarjetas de Crédito", "📅 Vencimientos", "🤖 Asistente IA"]
)

st.sidebar.markdown("---")
st.sidebar.info("Versión 0.1 - Modo Personal")

# --- SECCIÓN: TABLERO PRINCIPAL ---
if opcion == "📊 Tablero Principal":
    st.header("Resumen del Mes")
    
    # Métricas de ejemplo (Luego conectaremos tus datos reales)
    col1, col2, col3 = st.columns(3)
    col1.metric("Saldo en Cuentas", "$ 145,200", "Santander + Efectivo")
    col2.metric("A Pagar (Este mes)", "$ 45,427", "Alquiler + UTE")
    col3.metric("Deuda Tarjetas", "$ 38,500", "Cierre Próximo")

    st.markdown("### 🔔 Alertas Urgentes")
    st.warning("⚠️ La UTE vence en 3 días ($2,872)")

# --- SECCIÓN: INGRESAR MOVIMIENTOS ---
elif opcion == "💸 Ingresar Gasto/Ingreso":
    st.header("Registrar Movimiento")
    
    tipo_mov = st.radio("Tipo:", ["Gasto Saliente", "Ingreso Entrante", "Transferencia"], horizontal=True)
    
    col1, col2 = st.columns(2)
    with col1:
        monto = st.number_input("Monto", min_value=0.0, format="%.2f")
        moneda = st.selectbox("Moneda", ["UYU", "USD"])
    with col2:
        fecha = st.date_input("Fecha", datetime.today())
        categoria = st.selectbox("Categoría", ["Supermercado", "Servicios", "Auto", "Comida", "Salud", "Educación"])

    descripcion = st.text_input("Descripción (ej. Supermercado Disco)")
    
    # Lógica inteligente de cuentas
    if tipo_mov == "Gasto Saliente":
        metodo_pago = st.selectbox("¿Cómo pagaste?", ["Efectivo", "Santander Débito", "Visa Itaú", "Oca", "BBVA"])
        if "Visa" in metodo_pago or "Oca" in metodo_pago or "BBVA" in metodo_pago:
            st.info(f"ℹ️ Este gasto se sumará a la deuda de {metodo_pago} y no descontará dinero ahora.")
        else:
            st.info(f"ℹ️ Se descontará inmediatamente de {metodo_pago}.")

    if st.button("Guardar Movimiento", use_container_width=True):
        st.success("✅ Movimiento registrado (Simulación)")

# --- SECCIÓN: TARJETAS DE CRÉDITO ---
elif opcion == "💳 Tarjetas de Crédito":
    st.header("Gestión de Tarjetas")
    
    tab1, tab2 = st.tabs(["Estado Actual", "Cargar Estado de Cuenta"])
    
    with tab1:
        st.subheader("Visa Itaú - Vencimiento: 11/09/2025")
        
        col_uyu, col_usd = st.columns(2)
        with col_uyu:
            st.markdown("#### 🇺🇾 Pesos Uruguayos")
            st.metric("Deuda Total", "$ 38,520")
            st.metric("Pago Mínimo", "$ 1,500")
            opcion_pago_uyu = st.radio("Pago UYU:", ["Pagar Total", "Pagar Mínimo", "Otro Monto"], key="pago_uyu")
        
        with col_usd:
            st.markdown("#### 🇺🇸 Dólares")
            st.metric("Deuda Total", "U$S 207.00")
            st.metric("Pago Mínimo", "U$S 15.00")
            opcion_pago_usd = st.radio("Pago USD:", ["Pagar Total", "Pagar Mínimo", "Otro Monto"], key="pago_usd")
            
        st.divider()
        st.write("Simulación de Pago:")
        if st.checkbox("Simular impacto financiero"):
            st.warning("Si pagas solo el mínimo en Pesos, generarás aprox. $2,400 de intereses el próximo mes.")

# --- SECCIÓN: ASISTENTE IA ---
elif opcion == "🤖 Asistente IA":
    st.header("Consultor Financiero")
    st.markdown("""
    Pregúntame cosas como:
    * *"¿Cómo vengo de gastos comparado al mes pasado?"*
    * *"Si pago el total de la Oca, ¿me da para el alquiler?"*
    """)
    
    pregunta = st.text_input("Escribe tu consulta aquí...")
    if pregunta:
        st.write("🤖 *Analizando tus finanzas... (Próximamente conectado a Gemini)*")
