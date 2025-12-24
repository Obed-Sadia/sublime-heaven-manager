import streamlit as st
from supabase import create_client, Client
import pandas as pd
import plotly.express as px
from datetime import datetime
import pytz

# --- CONFIGURATION & SETUP ---
st.set_page_config(page_title="Gestion Sublime Heaven", page_icon="💄", layout="wide")

# Initialisation Supabase
@st.cache_resource
def init_connection():
    url = st.secrets["supabase"]["url"]
    key = st.secrets["supabase"]["key"]
    return create_client(url, key)

supabase = init_connection()

# --- AUTHENTIFICATION SIMPLE ---
def check_password():
    """Retourne True si l'utilisateur est connecté."""
    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False

    if not st.session_state.authenticated:
        password = st.text_input("🔒 Mot de passe", type="password")
        if st.button("Se connecter"):
            if password == st.secrets["supabase"]["app_password"]:
                st.session_state.authenticated = True
                st.rerun()
            else:
                st.error("Mot de passe incorrect")
        return False
    return True

if not check_password():
    st.stop()

# --- FONCTIONS UTILITAIRES ---
def get_inventory():
    response = supabase.table("inventory").select("*").execute()
    return pd.DataFrame(response.data)

def get_orders():
    # On joint les tables pour avoir le nom du produit
    response = supabase.table("orders").select("*, inventory(product_name)").execute()
    data = response.data
    # Aplatir le JSON retourné
    for row in data:
        if row['inventory']:
            row['product_name'] = row['inventory']['product_name']
        else:
            row['product_name'] = "Produit Supprimé"
    return pd.DataFrame(data)

# --- INTERFACE ---
st.sidebar.title("Sublime Heaven 💄")
page = st.sidebar.radio("Navigation", ["📝 Opérations (Vente)", "📦 Stocks", "📊 Analytics (Canada)"])

# --- PAGE 1 : OPÉRATIONS (VUE SŒUR) ---
if page == "📝 Opérations (Vente)":
    st.header("Nouvelle Vente / Dépense")
    
    tab1, tab2 = st.tabs(["🛒 Enregistrer Vente", "💸 Sortie Caisse"])
    
    # --- Formulaire Vente ---
    with tab1:
        # Chargement des produits pour le selectbox
        df_inv = get_inventory()
        if not df_inv.empty:
            active_products = df_inv[df_inv['quantity'] > 0]
            product_options = {row['product_name']: row for index, row in active_products.iterrows()}
            
            with st.form("sell_form"):
                st.info("Saisir les détails de la commande")
                col1, col2 = st.columns(2)
                with col1:
                    phone = st.text_input("Téléphone Client (ID)", placeholder="0707...")
                    product_name = st.selectbox("Produit", list(product_options.keys()))
                    source = st.selectbox("Source Marketing", ["Facebook", "TikTok", "Instagram", "Bouche à oreille", "Site Web (Direct)"])
                with col2:
                    qty = st.number_input("Quantité", min_value=1, value=1)
                    # Calcul prix auto
                    selected_prod = product_options[product_name] if product_name else None
                    unit_price = selected_prod['sell_price_cfa'] if selected_prod is not None else 0
                    manual_price = st.number_input("Prix Total (CFA)", value=int(unit_price * qty))
                
                submitted = st.form_submit_button("✅ Valider la vente")
                
                if submitted:
                    if not phone:
                        st.error("Le numéro de téléphone est obligatoire.")
                    else:
                        try:
                            # Appel de la fonction RPC (Transaction Atomique)
                            prod_id = int(selected_prod['id'])
                            response = supabase.rpc("process_sale", {
                                "p_phone": phone,
                                "p_product_id": prod_id,
                                "p_qty": int(qty),
                                "p_total": int(manual_price),
                                "p_source": source
                            }).execute()
                            
                            result = response.data
                            if result['success']:
                                st.success(f"Vente enregistrée ! Stock restant : {selected_prod['quantity'] - qty}")
                                # Petit hack pour vider le cache et recharger le stock frais
                                st.cache_data.clear()
                            else:
                                st.error(f"Erreur : {result['message']}")
                        except Exception as e:
                            st.error(f"Erreur de connexion : {e}")
        else:
            st.warning("Aucun produit en stock. Ajoutez-en dans l'onglet Stocks.")

    # --- Formulaire Dépense ---
    with tab2:
        with st.form("expense_form"):
            cat = st.selectbox("Catégorie", ["Transport", "Internet/Data", "Emballage", "Marketing", "Autre"])
            montant = st.number_input("Montant (CFA)", min_value=0)
            desc = st.text_input("Description (facultatif)")
            submit_expense = st.form_submit_button("Enregistrer Dépense")
            
            if submit_expense:
                try:
                    supabase.table("cashflow").insert({
                        "type": "SORTIE",
                        "category": cat,
                        "amount_cfa": montant,
                        "description": desc,
                        "date": datetime.now(pytz.utc).isoformat()
                    }).execute()
                    st.success("Dépense enregistrée.")
                except Exception as e:
                    st.error(f"Erreur : {e}")

# --- PAGE 2 : STOCKS ---
elif page == "📦 Stocks":
    st.header("État des Stocks")
    
    # 1. Ajout de Stock
    with st.expander("➕ Réapprovisionner / Nouveau Produit"):
        with st.form("add_stock"):
            new_name = st.text_input("Nom du produit")
            c1, c2, c3 = st.columns(3)
            new_qty = c1.number_input("Quantité Ajoutée", min_value=1)
            buy_p = c2.number_input("Prix Achat Unitaire", min_value=0)
            sell_p = c3.number_input("Prix Vente Unitaire", min_value=0)
            
            if st.form_submit_button("Ajouter au Stock"):
                # Logique simplifiée: ici on insère juste. 
                # Pour un vrai système, il faudrait vérifier si le produit existe déjà et faire un UPDATE.
                supabase.table("inventory").insert({
                    "product_name": new_name,
                    "quantity": new_qty,
                    "buy_price_cfa": buy_p,
                    "sell_price_cfa": sell_p
                }).execute()
                st.success("Stock mis à jour.")
                st.cache_data.clear()

    # 2. Visualisation
    df = get_inventory()
    if not df.empty:
        # Mise en forme conditionnelle
        def highlight_low_stock(val):
            color = 'red' if val < 5 else 'black' # Seuil en dur ici, à améliorer
            return f'color: {color}'

        st.dataframe(
            df.style.map(highlight_low_stock, subset=['quantity']),
            use_container_width=True,
            column_config={
                "product_name": "Produit",
                "quantity": "Stock",
                "buy_price_cfa": "P. Achat",
                "sell_price_cfa": "P. Vente"
            }
        )
    else:
        st.info("Inventaire vide.")

# --- PAGE 3 : ANALYTICS (CANADA) ---
elif page == "📊 Analytics (Canada)":
    st.header("Tableau de Bord Stratégique")
    
    df_orders = get_orders()
    
    if not df_orders.empty:
        # Conversion dates
        df_orders['created_at'] = pd.to_datetime(df_orders['created_at'])
        
        # KPIs
        total_ca = df_orders['total_amount_cfa'].sum()
        # Calcul marge approximatif (Vente - Coût d'achat enregistré)
        # Note: Si unit_buy_cost_at_sale est null (vieux data), on assume 0 pour éviter crash
        df_orders['margin'] = df_orders['total_amount_cfa'] - (df_orders['unit_buy_cost_at_sale'].fillna(0) * df_orders['quantity_sold'])
        total_profit = df_orders['margin'].sum()
        
        c1, c2, c3 = st.columns(3)
        c1.metric("Chiffre d'Affaires", f"{total_ca:,.0f} CFA")
        c2.metric("Marge Brute (Est.)", f"{total_profit:,.0f} CFA")
        c3.metric("Commandes", len(df_orders))
        
        st.divider()
        
        # Graphiques Marketing
        col_graph1, col_graph2 = st.columns(2)
        
        with col_graph1:
            st.subheader("Performance par Source")
            fig_pie = px.pie(df_orders, names='marketing_source', values='total_amount_cfa', title="CA par Source Marketing")
            st.plotly_chart(fig_pie, use_container_width=True)
            
        with col_graph2:
            st.subheader("Ventes dans le temps")
            # Grouper par jour
            daily_sales = df_orders.groupby(df_orders['created_at'].dt.date)['total_amount_cfa'].sum().reset_index()
            fig_bar = px.bar(daily_sales, x='created_at', y='total_amount_cfa', title="Évolution Journalière")
            st.plotly_chart(fig_bar, use_container_width=True)

    else:
        st.info("Aucune donnée de vente pour le moment.")
        