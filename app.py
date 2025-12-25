import streamlit as st
from supabase import create_client
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

# --- AUTHENTIFICATION ---
def check_password():
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

# --- FONCTIONS DONNÉES ---
def get_inventory():
    response = supabase.table("inventory").select("*").order('id').execute()
    return pd.DataFrame(response.data)

def get_orders():
    response = supabase.table("orders").select("*, inventory(product_name)").order('created_at', desc=True).execute()
    data = response.data
    for row in data:
        row['product_name'] = row['inventory']['product_name'] if row['inventory'] else "Produit Inconnu"
    return pd.DataFrame(data)

def get_pending_web_orders():
    # MODIFICATION : On récupère tout ce qui n'est pas terminé
    # Cela inclut "En attente", "En attente Web", "Nouveau", etc.
    response = supabase.table("orders")\
        .select("*, inventory(product_name, quantity, buy_price_cfa)")\
        .neq("status", "Livré")\
        .neq("status", "Annulé (Stock)")\
        .order('created_at', desc=True)\
        .execute()
    return response.data

# --- INTERFACE ---
st.sidebar.title("Sublime Heaven 💄")
page = st.sidebar.radio("Navigation", ["📝 Opérations (Journée)", "📦 Stocks", "📊 Analytics"])

# --- PAGE 1 : OPÉRATIONS ---
if page == "📝 Opérations (Journée)":
    st.header("Gestion Quotidienne")
    
    # On récupère les commandes web en attente
    pending_orders = get_pending_web_orders()
    count_pending = len(pending_orders)
    
    # Création des onglets (On ajoute l'onglet WEB en premier s'il y a des commandes)
    tab_labels = [f"🌐 Commandes Web ({count_pending})", "🛒 Vente Manuelle", "💸 Dépenses"]
    tab_web, tab_manual, tab_expense = st.tabs(tab_labels)
    
    # --- ONGLET 1 : COMMANDES WEB ---
    with tab_web:
        if count_pending == 0:
            st.info("Aucune commande en attente depuis le site web.")
        else:
            st.warning(f"⚠️ Vous avez {count_pending} commandes web à traiter !")
            
            for order in pending_orders:
                # Cadre visuel
                with st.expander(f"{order['created_at'][:16]} | {order['inventory']['product_name']} | {order['marketing_source']}", expanded=True):
                    
                    # Colonnes d'information
                    c1, c2, c3 = st.columns([2, 2, 3])
                    
                    prod_name = order['inventory']['product_name']
                    qty_sold = order['quantity_sold']
                    current_stock = order['inventory']['quantity']
                    buy_price = order['inventory']['buy_price_cfa']
                    
                    with c1:
                        st.write(f"**Produit:** {prod_name}")
                        st.write(f"**Quantité:** {qty_sold}")
                        st.caption(f"Stock actuel: {current_stock}")

                    with c2:
                        st.write(f"**Client:** {order['customer_phone']}")
                        # On affiche la source en GRAS pour que tu saches d'où ça vient
                        st.write(f"**Source:** :blue[{order['marketing_source']}]")
                    
                    with c3:
                        st.write("**Action à prendre :**")
                        col_btn_val, col_btn_cancel = st.columns(2)
                        
                        # --- BOUTON VALIDER (VERT) ---
                        if col_btn_val.button("✅ VALIDER", key=f"val_{order['id']}", type="primary"):
                            if current_stock >= qty_sold:
                                try:
                                    # 1. Déduire Stock
                                    supabase.table("inventory").update({"quantity": current_stock - qty_sold}).eq("id", order['product_id']).execute()
                                    # 2. Valider Commande
                                    supabase.table("orders").update({
                                        "status": "Livré",
                                        "unit_buy_cost_at_sale": buy_price 
                                    }).eq("id", order['id']).execute()
                                    st.success("Validé !")
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"Erreur: {e}")
                            else:
                                st.error("Stock insuffisant !")

                        # --- BOUTON ANNULER (ROUGE) ---
                        if col_btn_cancel.button("❌ ANNULER", key=f"can_{order['id']}"):
                            try:
                                # On change juste le statut, ON NE TOUCHE PAS AU STOCK
                                supabase.table("orders").update({
                                    "status": "Annulé (Client)"
                                }).eq("id", order['id']).execute()
                                st.warning("Commande annulée.")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Erreur: {e}")
                                
    # --- ONGLET 2 : VENTE MANUELLE (Ton ancien code) ---
    with tab_manual:
        df_inv = get_inventory()
        if not df_inv.empty:
            active_products = df_inv[df_inv['quantity'] > 0]
            product_options = {row['product_name']: row for index, row in active_products.iterrows()}
            
            with st.form("sell_form"):
                st.write("Saisir une vente faite par téléphone/WhatsApp (hors site)")
                col1, col2 = st.columns(2)
                with col1:
                    phone = st.text_input("Téléphone Client", placeholder="0707...")
                    product_name = st.selectbox("Produit", list(product_options.keys()))
                    source = st.selectbox("Source", ["Appel Direct", "Bouche à oreille", "Inconnu"])
                with col2:
                    qty = st.number_input("Quantité", min_value=1, value=1)
                    selected_prod = product_options[product_name] if product_name else None
                    unit_price = selected_prod['sell_price_cfa'] if selected_prod is not None else 0
                    manual_price = st.number_input("Prix Total (CFA)", value=int(unit_price * qty))
                
                submitted = st.form_submit_button("Enregistrer Vente Manuelle")
                
                if submitted:
                    if not phone:
                        st.error("Téléphone obligatoire.")
                    else:
                        try:
                            # Utilisation de la RPC pour vente manuelle directe
                            prod_id = selected_prod['id']
                            response = supabase.rpc("process_sale", {
                                "p_phone": phone, "p_product_id": prod_id,
                                "p_qty": int(qty), "p_total": int(manual_price),
                                "p_source": source
                            }).execute()
                            if response.data['success']:
                                st.success("Vente enregistrée !")
                                st.cache_data.clear()
                            else:
                                st.error(response.data['message'])
                        except Exception as e:
                            st.error(f"Erreur : {e}")

    # --- ONGLET 3 : DÉPENSES ---
    with tab_expense:
        with st.form("expense_form"):
            cat = st.selectbox("Catégorie", ["Transport", "Internet/Data", "Emballage", "Marketing", "Autre"])
            montant = st.number_input("Montant (CFA)", min_value=0)
            desc = st.text_input("Description")
            if st.form_submit_button("Enregistrer Dépense"):
                supabase.table("cashflow").insert({
                    "type": "SORTIE", "category": cat,
                    "amount_cfa": montant, "description": desc,
                    "date": datetime.now(pytz.utc).isoformat()
                }).execute()
                st.success("Dépense notée.")

# --- PAGE 2 : STOCKS ---
elif page == "📦 Stocks":
    st.header("État des Stocks")
    with st.expander("➕ Réapprovisionnement"):
        with st.form("add_stock"):
            new_name = st.text_input("Nom du produit (Ex: Savon Noir)")
            c1, c2, c3 = st.columns(3)
            new_qty = c1.number_input("Quantité Ajoutée", min_value=1)
            buy_p = c2.number_input("Prix Achat (Coût)", min_value=0)
            sell_p = c3.number_input("Prix Vente (Cible)", min_value=0)
            
            if st.form_submit_button("Ajouter Stock"):
                # Vérifier si produit existe déjà (par nom simple)
                existing = supabase.table("inventory").select("*").ilike("product_name", new_name).execute()
                if existing.data:
                    # Update
                    pid = existing.data[0]['id']
                    old_qty = existing.data[0]['quantity']
                    supabase.table("inventory").update({
                        "quantity": old_qty + new_qty,
                        "buy_price_cfa": buy_p, "sell_price_cfa": sell_p
                    }).eq("id", pid).execute()
                    st.success(f"Stock mis à jour pour {new_name}")
                else:
                    # Insert
                    supabase.table("inventory").insert({
                        "product_name": new_name, "quantity": new_qty,
                        "buy_price_cfa": buy_p, "sell_price_cfa": sell_p
                    }).execute()
                    st.success(f"Nouveau produit créé : {new_name}")
                st.cache_data.clear()

    df = get_inventory()
    if not df.empty:
        st.dataframe(df, use_container_width=True)

# --- PAGE 3 : ANALYTICS ---
elif page == "📊 Analytics":
    st.header("Tableau de Bord")
    df_orders = get_orders()
    if not df_orders.empty:
        df_orders['created_at'] = pd.to_datetime(df_orders['created_at'])
        # On ne compte que les ventes LIVRÉES pour le vrai CA
        df_delivered = df_orders[df_orders['status'] == 'Livré'].copy()
        
        ca = df_delivered['total_amount_cfa'].sum()
        count = len(df_delivered)
        
        c1, c2 = st.columns(2)
        c1.metric("Chiffre d'Affaires (Validé)", f"{ca:,.0f} CFA")
        c2.metric("Ventes Validées", count)
        
        st.divider()
        st.subheader("Ventes par Source")
        fig = px.pie(df_delivered, names='marketing_source', values='total_amount_cfa')
        st.plotly_chart(fig)
    else:
        st.info("Pas encore de données.")