import streamlit as st
from supabase import create_client
import pandas as pd
import plotly.express as px
from datetime import datetime
import pytz
import plotly.express as px
import plotly.graph_objects as go
import google.generativeai as genai

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

def get_all_web_orders():
    # On récupère TOUTES les commandes web (pour l'historique et la recherche)
    response = supabase.table("orders")\
        .select("*, inventory(product_name, quantity, buy_price_cfa)")\
        .order('created_at', desc=True)\
        .execute()
    return pd.DataFrame(response.data)

# --- INTERFACE ---
st.sidebar.title("Sublime Heaven 💄")
page = st.sidebar.radio("Navigation", ["📝 Opérations", "📦 Stocks", "📊 Analytics", "🤖 Assistant IA"])


# --- PAGE 1 : OPÉRATIONS MODIFIÉE ---
if page == "📝 Opérations":
    st.header("Gestion Quotidienne")
    
    # 1. Barre de Recherche Globale
    search_query = st.text_input("🔍 Rechercher une commande (N° Tel, Ref commande, Nom produit)", placeholder="Ex: 5656 ou 0707...")

    # 2. Récupération des données
    df_all = get_all_web_orders()
    
    if not df_all.empty:
        # Conversion dates
        df_all['created_at'] = pd.to_datetime(df_all['created_at'])
        
        # --- FILTRE DE RECHERCHE ---
        if search_query:
            # On cherche dans le téléphone, la ref, ou le nom du produit
            mask = (
                df_all['customer_phone'].astype(str).str.contains(search_query, case=False) |
                df_all['order_ref'].astype(str).str.contains(search_query, case=False) |
                df_all['inventory'].apply(lambda x: x['product_name'] if x else '').str.contains(search_query, case=False)
            )
            df_display = df_all[mask]
            st.info(f"Résultats de recherche : {len(df_display)} commande(s) trouvée(s)")
        else:
            # Si pas de recherche, on affiche par défaut les "En attente"
            df_display = df_all
        
        # Séparation des commandes (En cours vs Terminées)
        # Note : On exclut 'Livré' et 'Annulé' pour l'onglet "A Traiter", sauf si on fait une recherche
        if search_query:
            pending_orders = df_display # En recherche, on montre tout ce qui matche
        else:
            pending_orders = df_display[~df_display['status'].isin(['Livré', 'Annulé (Client)', 'Annulé (Stock)'])]
            
        completed_orders = df_all[df_all['status'].isin(['Livré', 'Annulé (Client)', 'Annulé (Stock)'])]

        # --- ONGLET 1 : À TRAITER ---
        # Calcul du nombre pour le badge
        count_pending = len(pending_orders)
        
        tab_web, tab_history, tab_manual, tab_expense = st.tabs([
            f"⚡ À Traiter ({count_pending})", 
            "📂 Historique / Terminées",
            "🛒 Vente Manuelle", 
            "💸 Dépenses"
        ])
        
        # --- CONTENU ONGLET À TRAITER ---
        with tab_web:
            if pending_orders.empty:
                st.success("🎉 Tout est à jour ! Aucune commande en attente.")
            else:
                for index, order in pending_orders.iterrows():
                    # Carte visuelle
                    ref_display = f"#{order['order_ref']}" if order['order_ref'] else "Sans Ref"
                    
                    with st.expander(f"{ref_display} | {order['customer_phone']} | {order['inventory']['product_name']}", expanded=True):
                        c1, c2, c3 = st.columns([2, 2, 3])
                        
                        prod_name = order['inventory']['product_name']
                        qty_sold = order['quantity_sold']
                        current_stock = order['inventory']['quantity']
                        buy_price = order['inventory']['buy_price_cfa']
                        
                        with c1:
                            st.write(f"**Produit:** {prod_name}")
                            st.write(f"**Quantité:** {qty_sold}")
                            if current_stock < qty_sold:
                                st.error(f"Stock critique : {current_stock}")
                            else:
                                st.caption(f"Stock dispo : {current_stock}")

                        with c2:
                            st.write(f"**Client:** {order['customer_phone']}")
                            st.write(f"**Source:** :blue[{order['marketing_source']}]")
                            st.caption(f"Date: {order['created_at'].strftime('%d/%m %H:%M')}")
                        
                        with c3:
                            col_val, col_can = st.columns(2)
                            if col_val.button("✅ LIVRÉ", key=f"v_{order['id']}", type="primary"):
                                if current_stock >= qty_sold:
                                    supabase.table("inventory").update({"quantity": current_stock - qty_sold}).eq("id", order['product_id']).execute()
                                    supabase.table("orders").update({"status": "Livré", "unit_buy_cost_at_sale": buy_price}).eq("id", order['id']).execute()
                                    st.toast("Validé !")
                                    st.rerun()
                                else:
                                    st.error("Stock insuffisant")

                            if col_can.button("❌ ANNULER", key=f"c_{order['id']}"):
                                supabase.table("orders").update({"status": "Annulé (Client)"}).eq("id", order['id']).execute()
                                st.rerun()

        # --- CONTENU ONGLET HISTORIQUE ---
        with tab_history:
            st.write("Dernières commandes terminées")
            # On affiche un tableau propre pour l'historique
            st.dataframe(
                completed_orders[['created_at', 'order_ref', 'customer_phone', 'product_id', 'total_amount_cfa', 'status', 'marketing_source']],
                column_config={
                    "created_at": st.column_config.DatetimeColumn("Date", format="D MMM, HH:mm"),
                    "order_ref": "Réf",
                    "customer_phone": "Client",
                    "product_id": "Code Produit",
                    "total_amount_cfa": st.column_config.NumberColumn("Montant", format="%d CFA"),
                    "status": "Etat",
                    "marketing_source": "Source"
                },
                use_container_width=True,
                height=400
            )

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
        

# --- PAGE 4 : ASSISTANT IA (VERSION GEMINI) ---
elif page == "🤖 Assistant IA":
    st.header("Ton Assistant Intelligent (Propulsé par Gemini) 💎")
    
    # Configuration de la clé API
    if "gemini" in st.secrets:
        genai.configure(api_key=st.secrets["gemini"]["api_key"])
    else:
        st.error("⚠️ Clé Gemini manquante. Ajoute-la dans les secrets (.streamlit/secrets.toml).")
        st.info("Format: [gemini] api_key = 'AIza...'")
        st.stop()

    tab_cfo, tab_cmo = st.tabs(["📊 Analyste (Talk to Data)", "🎥 Marketing (Content Factory)"])

    # --- CERVEAU 1 : L'ANALYSTE (Text-to-Code) ---
    with tab_cfo:
        st.subheader("Posez une question à vos données")
        st.caption("Exemples : 'Quel est le produit le plus vendu ?', 'Montre-moi les ventes par source', 'Moyenne des paniers ?'")
        
        df_orders = get_orders()
        
        user_question = st.text_area("Ta question :", placeholder="Écris ta question ici...")
        
        if st.button("Analyses-moi ça 🚀"):
            if user_question and not df_orders.empty:
                with st.spinner("Gemini réfléchit..."):
                    try:
                        # 1. Préparation du contexte
                        columns_info = list(df_orders.columns)
                        sample_data = df_orders.head(3).to_markdown()
                        
                        prompt = f"""
                        Tu es un expert en Data Science Python (Pandas/Plotly).
                        Tu as accès à une DataFrame nommée 'df'.
                        Colonnes : {columns_info}
                        Exemple de données :
                        {sample_data}
                        
                        Question : "{user_question}"
                        
                        Consignes STRICTES :
                        1. Écris UNIQUEMENT le code Python exécutable. Pas de texte avant ou après.
                        2. Pas de balises markdown (pas de ```python).
                        3. Utilise 'st.write()' pour afficher du texte/chiffres.
                        4. Utilise 'st.plotly_chart()' pour les graphiques (avec plotly.express as px).
                        5. La variable de données s'appelle 'df'.
                        """
                        
                        # 2. Appel à Gemini 
                        model = genai.GenerativeModel('gemini-2.0-flash')
                        response = model.generate_content(prompt)
                        
                        # 3. Nettoyage
                        generated_code = response.text.replace("```python", "").replace("```", "").strip()
                        
                        st.code(generated_code, language="python")
                        st.divider()
                        
                        # 4. Exécution
                        local_vars = {"df": df_orders, "px": px, "st": st, "pd": pd}
                        exec(generated_code, globals(), local_vars)
                        
                    except Exception as e:
                        st.error(f"Erreur : {e}")
                        st.caption("Si l'erreur persiste, vérifie ta clé API ou essaie une question plus simple.")

    # --- CERVEAU 2 : LE MARKETEUR (Content Gen) ---
    with tab_cmo:
        st.subheader("Générateur de Scripts Viraux 📱")
        
        df_inv = get_inventory()
        product_list = df_inv['product_name'].tolist()
        selected_prod = st.selectbox("Quel produit veux-tu pousser ?", product_list)
        
        angle = st.selectbox("Quel angle marketing ?", [
            "😱 Le Choc (Hook visuel)",
            "storytelling (Témoignage émouvant)",
            "educational (Le saviez-vous ?)",
            "humour (Ivoirien)"
        ])
        
        context_perplexity = st.text_area("Info Perplexity (Optionnel)", placeholder="Colle ici une info trouvée sur Perplexity (ex: Tendance TikTok du moment...)")

        if st.button("Génère le script ✨"):
            with st.spinner("Rédaction en cours..."):
                base_prompt = f"""
                Agis comme un expert TikTok ivoirien pour la marque 'Sublime Haven'.
                Produit : {selected_prod}
                Angle : {angle}
                
                Structure du script (30s) :
                1. HOOK : Phrase choc.
                2. BODY : Bénéfice produit (pas de jargon technique).
                3. CTA : Appel à l'action.
                
                Ton : Amical, direct, utilisation modérée de l'argot ivoirien (Nouchi léger).
                Utilise des emojis.
                """
                
                if context_perplexity:
                    base_prompt += f"\nIntègre cette tendance/info : {context_perplexity}"

                
                model = genai.GenerativeModel('gemini-2.0-flash') 
                response_market = model.generate_content(base_prompt)
                
                st.markdown(response_market.text)