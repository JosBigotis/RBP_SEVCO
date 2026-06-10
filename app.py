import streamlit as st
from supabase import create_client, Client
import json
import random
import time
import math
import pandas as pd

# --- Database Initialization ---
@st.cache_resource
def init_connection() -> Client:
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    return create_client(url, key)

supabase = init_connection()

SHAPES = ["⭐ Étoile", "⭕ Cercle", "⬛ Carré", "🔺 Triangle", "💖 Cœur"]

# --- STV Tally Algorithm ---
def run_stv_tally(valid_ballots, seats):
    if not valid_ballots:
        return "Aucun vote valide."
    
    # Format valid_ballots for counting: list of dicts with 'ranking' and 'weight'
    ballots = [{'ranking': b, 'weight': 1.0} for b in valid_ballots]
    
    candidates_data = supabase.table('candidates').select('name').execute().data
    active_candidates = set([c['name'] for c in candidates_data])
    elected = []
    tally_log = [f"Sièges à pourvoir: {seats} | Bulletins valides: {len(ballots)}"]

    quota = math.floor(len(ballots) / (seats + 1)) + 1
    tally_log.append(f"Quota de Droop: {quota}")

    round_num = 1
    while len(elected) < seats and active_candidates:
        tally_log.append(f"\n--- Tour {round_num} ---")
        counts = {c: 0.0 for c in active_candidates}
        
        for b in ballots:
            for choice in b['ranking']:
                if choice in active_candidates or choice in elected:
                    if choice in active_candidates: counts[choice] += b['weight']
                    break
        
        round_winners = []
        for c, v in counts.items():
            tally_log.append(f"{c}: {v:.2f} votes")
            if v >= quota: round_winners.append(c)

        if round_winners:
            for winner in round_winners:
                if len(elected) >= seats: break
                elected.append(winner)
                active_candidates.remove(winner)
                surplus = counts[winner] - quota
                transfer_rate = surplus / counts[winner] if counts[winner] > 0 else 0
                tally_log.append(f"ÉLU: {winner} (Surplus: {surplus:.2f})")
                for b in ballots:
                    for choice in b['ranking']:
                        if choice == winner:
                            b['weight'] *= transfer_rate
                            break
                        elif choice in active_candidates:
                            break
        else:
            if not counts: break
            lowest = min(counts, key=counts.get)
            tally_log.append(f"Élimination: {lowest}")
            active_candidates.remove(lowest)

        if 0 < len(active_candidates) <= (seats - len(elected)):
            for c in list(active_candidates):
                elected.append(c)
                active_candidates.remove(c)
                tally_log.append(f"ÉLU: {c} (Par défaut)")
        round_num += 1

    tally_log.append(f"\nRÉSULTAT FINAL: {', '.join(elected)}")
    return "\n".join(tally_log)


# --- Router ---
st.set_page_config(page_title="Système de Vote RBAC", layout="wide")
st.sidebar.title("Navigation Réseau")
node = st.sidebar.radio("Aller vers:", ["Portail Votant", "Moniteur d'Infrastructure (Projecteur)", "Panneau Administrateur"])

# ==========================================
# NODE 1: ADMIN DASHBOARD
# ==========================================
if node == "Panneau Administrateur":
    st.title("🛡️ Nœud Administrateur")
    pwd = st.text_input("Mot de passe", type="password")
    
    if pwd == "admin123":
        st.success("Authentifié.")
        
        col1, col2 = st.columns(2)
        with col1:
            st.subheader("Candidats (Max 5)")
            new_cand = st.text_input("Nom du candidat")
            if st.button("Ajouter Candidat"):
                supabase.table('candidates').insert({'name': new_cand}).execute()
                st.rerun()
            cands = supabase.table('candidates').select('name').execute().data
            st.write([c['name'] for c in cands])
            if st.button("Effacer Candidats"):
                supabase.table('candidates').delete().neq('name', '0').execute()
                st.rerun()

        with col2:
            st.subheader("Votants Inscrits")
            new_voter = st.text_input("ID Votant (ex: Alice123)")
            if st.button("Inscrire Votant"):
                supabase.table('voters').insert({'voter_id': new_voter}).execute()
                st.rerun()
            voters = supabase.table('voters').select('voter_id').execute().data
            st.write([v['voter_id'] for v in voters])
            if st.button("Effacer Votants"):
                supabase.table('voters').delete().neq('voter_id', '0').execute()
                st.rerun()

        st.divider()
        seats = st.number_input("Nombre de sièges", min_value=1, value=1)
        
        if st.button("🚀 DÉMARRER L'ÉLECTION (Générer les Combinaisons)", type="primary"):
            # 1. Reset states
            supabase.table('ballots').delete().neq('id', '0').execute()
            supabase.table('voter_receipts').delete().neq('voter_id', '0').execute()
            supabase.table('combinations').delete().neq('comb_id', '0').execute()
            supabase.table('system_state').upsert({'key': 'status', 'value': 'Ouvert'}).execute()
            supabase.table('system_state').upsert({'key': 'seats', 'value': str(seats)}).execute()
            
            # 2. Generate Combinations and distribute limits
            voter_ids = [v['voter_id'] for v in supabase.table('voters').select('voter_id').execute().data]
            cand_names = [c['name'] for c in supabase.table('candidates').select('name').execute().data]
            
            if len(cand_names) > 5 or len(cand_names) == 0:
                st.error("Erreur: Il faut entre 1 et 5 candidats.")
                st.stop()
                
            num_combs = max(1, len(voter_ids) // 2) # At least 2 voters per comb average
            alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
            
            for i in range(num_combs):
                comb_id = alphabet[i]
                random.shuffle(cand_names)
                mapping = {SHAPES[j]: cand_names[j] for j in range(len(cand_names))}
                # Limit is strictly tracked globally by the counting authorities
                supabase.table('combinations').insert({
                    'comb_id': comb_id,
                    'mapping': mapping,
                    'max_limit': 0 # We will increment this as we assign voters
                }).execute()

            # Assign voters to combinations
            for v_id in voter_ids:
                assigned_c_id = alphabet[random.randint(0, num_combs - 1)]
                supabase.table('voters').update({'assigned_comb': assigned_c_id, 'has_voted': False}).eq('voter_id', v_id).execute()
                # Increment the authorized limit for this comb
                current_limit = supabase.table('combinations').select('max_limit').eq('comb_id', assigned_c_id).execute().data[0]['max_limit']
                supabase.table('combinations').update({'max_limit': current_limit + 1}).eq('comb_id', assigned_c_id).execute()

            st.success("L'élection est ouverte ! Combinaisons générées secrètement.")

        if st.button("Clôturer l'Élection"):
            supabase.table('system_state').upsert({'key': 'status', 'value': 'Fermé'}).execute()
            st.success("Élection clôturée.")


# ==========================================
# NODE 2: VOTER PORTAL
# ==========================================
elif node == "Portail Votant":
    st.title("🗳️ Portail Votant")
    
    status_req = supabase.table('system_state').select('value').eq('key', 'status').execute().data
    status = status_req[0]['value'] if status_req else "Fermé"
    
    if status == "Fermé":
        st.error("L'élection n'est pas en cours.")
        st.stop()

    if "voter_id" not in st.session_state:
        v_id = st.text_input("Entrez votre ID Votant (ex: Nom123)")
        if st.button("S'authentifier"):
            voter_data = supabase.table('voters').select('*').eq('voter_id', v_id).execute().data
            if not voter_data:
                st.error("ID non reconnu.")
            elif voter_data[0]['has_voted']:
                st.error("Vous avez déjà voté.")
            else:
                st.session_state.voter_id = v_id
                st.session_state.assigned_comb = voter_data[0]['assigned_comb']
                st.rerun()
    else:
        tab1, tab2 = st.tabs(["🎫 Centre de Remise des Billets", "✉️ Isoloir (Vote)"])
        
        with tab1:
            st.subheader("Votre Billet Secret")
            st.info("Mémorisez votre ID de combinaison et vos correspondances. Le billet s'autodétruira dans 5 secondes.")
            
            placeholder = st.empty()
            if placeholder.button("Révéler mon Billet"):
                with placeholder.container():
                    st.write(f"### Votre ID de Combinaison : **{st.session_state.assigned_comb}**")
                    mapping_data = supabase.table('combinations').select('mapping').eq('comb_id', st.session_state.assigned_comb).execute().data[0]['mapping']
                    for shape, cand in mapping_data.items():
                        st.write(f"{shape} ➜ **{cand}**")
                
                time.sleep(5)
                placeholder.empty()
                st.rerun()

        with tab2:
            st.subheader("Bulletin de Vote")
            st.write(f"**Votant:** {st.session_state.voter_id}")
            
            # Use only the shapes required for the number of candidates
            cands_count = len(supabase.table('candidates').select('name').execute().data)
            available_shapes = SHAPES[:cands_count]
            
            index_labels = [f"Choix {i}" for i in range(1, cands_count + 1)]
            if "ballot_df" not in st.session_state or list(st.session_state.ballot_df.columns) != available_shapes:
                st.session_state.ballot_df = pd.DataFrame(False, index=index_labels, columns=available_shapes)

            edited_df = st.data_editor(st.session_state.ballot_df, use_container_width=True)
            typed_comb_id = st.text_input("Saisissez votre ID de Combinaison (Lettre)")

            if st.button("Soumettre le Bulletin"):
                ranking = []
                valid = True
                for col in edited_df.columns:
                    if edited_df[col].sum() > 1: valid = False
                for i in range(len(edited_df)):
                    row = edited_df.iloc[i]
                    selected = row[row == True].index.tolist()
                    if len(selected) > 1: valid = False
                    elif selected: ranking.append(selected[0])
                
                if not valid or not ranking:
                    st.error("Bulletin invalide. Vérifiez vos choix.")
                elif not typed_comb_id:
                    st.error("Vous devez saisir un ID de combinaison.")
                else:
                    # 1. Post to Bulletin Board (Simulating the separation)
                    supabase.table('ballots').insert({
                        'comb_id': typed_comb_id.upper(),
                        'shapes_ranking': ranking
                    }).execute()
                    
                    # 2. Register Voter Receipt (Separated from the ballot)
                    supabase.table('voter_receipts').insert({'voter_id': st.session_state.voter_id}).execute()
                    supabase.table('voters').update({'has_voted': True}).eq('voter_id', st.session_state.voter_id).execute()
                    
                    del st.session_state.voter_id
                    st.success("A voté !")
                    time.sleep(2)
                    st.rerun()


# ==========================================
# NODE 3: INFRASTRUCTURE MONITOR
# ==========================================
elif node == "Moniteur d'Infrastructure (Projecteur)":
    st.title("👁️ Architecture de Dépouillement")
    if st.button("Rafraîchir les données en direct"):
        st.rerun()
    
    st.divider()
    st.subheader("1. Mix-Net (Anonymisation des Flux)")
    ballots = supabase.table('ballots').select('*').execute().data
    if ballots:
        # Simulate Mix-net shuffling
        shuffled = list(ballots)
        random.shuffle(shuffled)
        df_mix = pd.DataFrame([{"ID Combinaison": b['comb_id'], "Choix Formes": " > ".join(b['shapes_ranking'])} for b in shuffled])
        st.dataframe(df_mix, use_container_width=True)
    else:
        st.write("Le Mix-Net est vide.")

    st.divider()
    st.subheader("2. Autorités de Comptage (Vérification et Décodage)")
    combs = supabase.table('combinations').select('*').execute().data
    
    valid_candidate_ballots = []
    
    col1, col2, col3 = st.columns(3)
    cols = [col1, col2, col3]
    
    for i, comb in enumerate(combs):
        with cols[i % 3]:
            st.write(f"### Lot: {comb['comb_id']}")
            st.write(f"Limite autorisée: **{comb['max_limit']}**")
            
            comb_ballots = [b for b in ballots if b['comb_id'] == comb['comb_id']]
            st.write(f"Bulletins reçus: **{len(comb_ballots)}**")
            
            if len(comb_ballots) > comb['max_limit']:
                st.error("🚨 FRAUDE DÉTECTÉE ! Limite dépassée. Tous les votes de ce lot sont annulés.")
            else:
                st.success("Intégrité validée.")
                # Translate shapes to candidates
                for b in comb_ballots:
                    cand_ranking = [comb['mapping'].get(shape, shape) for shape in b['shapes_ranking']]
                    valid_candidate_ballots.append(cand_ranking)
                    st.caption(f"Décrypté: {' > '.join(cand_ranking)}")

    st.divider()
    st.subheader("3. Centre de Décompte (Tally)")
    
    # Vérifiabilité individuelle
    receipts = supabase.table('voter_receipts').select('voter_id').execute().data
    st.write("Votants ayant déposé un bulletin (Vérifiabilité individuelle) :")
    st.write(", ".join([r['voter_id'] for r in receipts]) if receipts else "Aucun déposant.")
    
    # Real-Time First Preference
    if valid_candidate_ballots:
        first_prefs = {}
        for b in valid_candidate_ballots:
            first = b[0]
            first_prefs[first] = first_prefs.get(first, 0) + 1
            
        st.write("### Intentions de 1er Choix (Temps Réel)")
        st.bar_chart(pd.DataFrame(list(first_prefs.items()), columns=["Candidat", "Votes"]).set_index("Candidat"))

    # STV Final Execution
    status_req = supabase.table('system_state').select('value').eq('key', 'status').execute().data
    if status_req and status_req[0]['value'] == "Fermé":
        seats = int(supabase.table('system_state').select('value').eq('key', 'seats').execute().data[0]['value'])
        st.write("### Décompte Officiel STV")
        st.text_area("Log de l'algorithme", run_stv_tally(valid_candidate_ballots, seats), height=300)
    else:
        st.warning("L'élection est toujours en cours. Le décompte STV final est verrouillé.")
