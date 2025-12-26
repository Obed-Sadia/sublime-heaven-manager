import streamlit as st
from supabase import create_client
import pandas as pd
import plotly.express as px
from datetime import datetime
import pytz
import plotly.express as px
import plotly.graph_objects as go

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
# --- PAGE 2 : STOCKS & GESTION ---
elif page == "📦 Stocks":
    st.header("Gestion de l'Inventaire")
    
    # 1. Récupération des données fraîches
    df = get_inventory()
    
    # --- TABLEAU DE BORD VISUEL ---
    if not df.empty:
        # On affiche d'abord le tableau pour avoir une vue d'ensemble
        st.dataframe(
            df, 
            use_container_width=True,
            column_config={
                "id": "Code (SKU)",
                "product_name": "Produit",
                "quantity": "Stock",
                "buy_price_cfa": st.column_config.NumberColumn("Prix Achat", format="%d CFA"),
                "sell_price_cfa": st.column_config.NumberColumn("Prix Vente", format="%d CFA"),
            }
        )
    else:
        st.info("Votre inventaire est vide.")

    st.divider()

    # --- ZONE D'ACTION ---
    st.subheader("Action sur le stock")
    
    # Choix du mode de travail
    mode = st.radio("Que voulez-vous faire ?", ["✏️ Modifier / Supprimer un produit", "➕ Créer un nouveau produit"], horizontal=True)

    # --- MODE 1 : MODIFIER / SUPPRIMER ---
    if mode == "✏️ Modifier / Supprimer un produit":
        if df.empty:
            st.warning("Rien à modifier.")
        else:
            # Liste déroulante intelligente : "Code - Nom du produit"
            product_list = [f"{row['id']} - {row['product_name']}" for index, row in df.iterrows()]
            selected_product_str = st.selectbox("Sélectionnez le produit à gérer", product_list)
            
            # On extrait l'ID (la partie avant le tiret)
            selected_id = selected_product_str.split(" - ")[0]
            
            # On récupère les infos actuelles de ce produit pour pré-remplir le formulaire
            current_data = df[df['id'] == selected_id].iloc[0]

            with st.form("edit_form"):
                st.caption(f"Modification de : **{current_data['product_name']}** (Code: {selected_id})")
                
                # Champs modifiables
                new_name = st.text_input("Nom du Produit", value=current_data['product_name'])
                
                c1, c2, c3 = st.columns(3)
                new_qty = c1.number_input("Stock Actuel", value=int(current_data['quantity']), step=1)
                new_buy = c2.number_input("Prix Achat (Coût)", value=int(current_data['buy_price_cfa']), step=500)
                new_sell = c3.number_input("Prix Vente (Client)", value=int(current_data['sell_price_cfa']), step=500)
                
                col_save, col_del = st.columns([1, 1])
                
                # BOUTON SAUVEGARDER
                if col_save.form_submit_button("💾 Enregistrer les changements", type="primary"):
                    try:
                        supabase.table("inventory").update({
                            "product_name": new_name,
                            "quantity": new_qty,
                            "buy_price_cfa": new_buy,
                            "sell_price_cfa": new_sell
                        }).eq("id", selected_id).execute()
                        st.success(f"Produit {selected_id} mis à jour!")
                        st.cache_data.clear() # Force le rechargement
                        st.rerun()
                    except Exception as e:
                        st.error(f"Erreur : {e}")

                # BOUTON SUPPRIMER
                if col_del.form_submit_button("🗑️ SUPPRIMER DÉFINITIVEMENT", type="secondary"):
                    try:
                        supabase.table("inventory").delete().eq("id", selected_id).execute()
                        st.warning(f"Produit {selected_id} supprimé.")
                        st.cache_data.clear()
                        st.rerun()
                    except Exception as e:
                        # Message d'erreur spécifique si le produit a déjà été vendu
                        st.error("Impossible de supprimer ce produit car il apparaît dans l'historique des ventes (Commandes).")
                        st.info("💡 Conseil : Au lieu de le supprimer, mettez son stock à 0 et ajoutez '(OBSOLÈTE)' à son nom.")

    # --- MODE 2 : CRÉER NOUVEAU ---
    elif mode == "➕ Créer un nouveau produit":
        with st.form("add_form"):
            st.write("Ajout d'une nouvelle référence au catalogue")
            
            c_code, c_name = st.columns([1, 3])
            new_id = c_code.text_input("Code (Ex: PR015)", placeholder="PR...")
            new_name = c_name.text_input("Nom du produit", placeholder="Ex: Nouveau Savon")
            
            c1, c2, c3 = st.columns(3)
            new_qty = c1.number_input("Stock de départ", min_value=0, value=0)
            new_buy = c2.number_input("Prix Achat", min_value=0, value=0)
            new_sell = c3.number_input("Prix Vente", min_value=0, value=0)
            
            if st.form_submit_button("Créer le produit"):
                if new_id and new_name:
                    try:
                        # Vérifier si l'ID existe déjà
                        existing = supabase.table("inventory").select("id").eq("id", new_id).execute()
                        if existing.data:
                            st.error(f"Erreur : Le code '{new_id}' existe déjà !")
                        else:
                            supabase.table("inventory").insert({
                                "id": new_id,
                                "product_name": new_name,
                                "quantity": new_qty,
                                "buy_price_cfa": new_buy,
                                "sell_price_cfa": new_sell
                            }).execute()
                            st.success(f"Produit {new_name} créé avec succès !")
                            st.cache_data.clear()
                            st.rerun()
                    except Exception as e:
                        st.error(f"Erreur : {e}")
                else:
                    st.warning("Le Code et le Nom sont obligatoires.")

# --- PAGE 3 : ANALYTICS ---
elif page == "📊 Analytics":
    st.title("Tableau de Bord Stratégique 🚀")
    
    # 1. CHARGEMENT DES DONNÉES
    # On récupère les commandes
    df_orders = get_orders() # Ta fonction existante
    
    # On récupère le trafic (Nouvelle requête)
    traffic_response = supabase.table("site_traffic").select("*").execute()
    df_traffic = pd.DataFrame(traffic_response.data)

    # --- SECTION 1 : KPIs GLOBAUX ---
    st.subheader("Performance Globale")
    
    if not df_orders.empty:
        # Calculs Financiers
        df_orders['created_at'] = pd.to_datetime(df_orders['created_at'])
        
        # Commandes Validées (L'argent réel)
        df_valide = df_orders[df_orders['status'] == 'Livré']
        ca_reel = df_valide['total_amount_cfa'].sum()
        
        # Commandes Totales (Le volume)
        ca_total = df_orders['total_amount_cfa'].sum()
        nb_total = len(df_orders)
        
        # Taux de Conversion (Commandes / Visiteurs Uniques)
        nb_visiteurs = len(df_traffic) if not df_traffic.empty else 1 # Évite division par 0
        taux_conv = (nb_total / nb_visiteurs) * 100
        
        kpi1, kpi2, kpi3, kpi4 = st.columns(4)
        kpi1.metric("Chiffre d'Affaires (Encaissé)", f"{ca_reel:,.0f} CFA", delta="Net Revenue")
        kpi2.metric("Volume de Commandes", f"{nb_total}", help="Toutes commandes confondues")
        kpi3.metric("Visiteurs Totaux", f"{nb_visiteurs}", help="Basé sur les logs")
        kpi4.metric("Taux de Conversion", f"{taux_conv:.2f} %")

    st.divider()

    # --- SECTION 2 : ANALYSE DES VENTES ---
    c1, c2 = st.columns(2)
    
    with c1:
        st.subheader("🏆 Top Produits")
        if not df_orders.empty:
            # On groupe par nom de produit et on somme les quantités
            top_products = df_orders.groupby('product_name')['quantity_sold'].sum().reset_index()
            fig_prod = px.bar(top_products, x='quantity_sold', y='product_name', orientation='h', 
                              title="Unités Vendues par Produit", color='quantity_sold')
            st.plotly_chart(fig_prod, use_container_width=True)

    with c2:
        st.subheader("📦 Statut des Commandes")
        if not df_orders.empty:
            status_counts = df_orders['status'].value_counts().reset_index()
            status_counts.columns = ['Statut', 'Nombre']
            fig_status = px.pie(status_counts, values='Nombre', names='Statut', hole=0.4, 
                                color='Statut', color_discrete_map={'Livré':'green', 'Annulé (Client)':'red', 'En attente Web':'orange'})
            st.plotly_chart(fig_status, use_container_width=True)

    # --- SECTION 3 : TRAFIC & MARKETING ---
    st.divider()
    st.subheader("🕵️ Analyse du Trafic & Sources")
    
    if not df_traffic.empty:
        t1, t2 = st.columns(2)
        
        with t1:
            st.markdown("**📍 D'où viennent tes visiteurs ?**")
            source_counts = df_traffic['source'].value_counts().reset_index()
            fig_source = px.pie(source_counts, values='count', names='source', title="Sources de Trafic")
            st.plotly_chart(fig_source, use_container_width=True)
            
        with t2:
            st.markdown("**📱 Quel appareil utilisent-ils ?**")
            # Graphique Appareil (Mobile vs Desktop)
            dev_counts = df_traffic['device_type'].value_counts().reset_index()
            fig_dev = px.bar(dev_counts, x='device_type', y='count', color='device_type', title="Sessions par Appareil")
            st.plotly_chart(fig_dev, use_container_width=True)

        # Graphique OS
        os_counts = df_traffic['os'].value_counts().reset_index()
        fig_os = px.bar(os_counts, x='os', y='count', title="Système d'Exploitation")
        st.plotly_chart(fig_os, use_container_width=True)
            
    else:
        st.info("En attente de données de trafic... (Vérifiez que le script JS est bien en place)")