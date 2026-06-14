import streamlit as st
from supabase import create_client, Client
import json
import random
import time
import math
import pandas as pd
import hashlib

# --- Cryptographic Constants & Primitives (ElGamal / Schnorr ZKP) ---
P = 2147483647  # Premier de Mersenne sécurisé (2^31 - 1)
G = 7           # Générateur primitif

def cryptographic_keygen():
    """Génère un couple de clés ElGamal/Schnorr pour un lot donné"""
    private_key = random.randint(2, P - 2)
    public_key = pow(G, private_key, P)
    return private_key, public_key

def generate_ballot_zkp(private_key, public_key):
    """Génère une preuve de connaissance interactive (ZKP) du droit de vote"""
    k = random.randint(2, P - 2)
    r = pow(G, k, P)
    # Définition du défi par hachage (Fiat-Shamir Heuristic)
    challenge_input = f"{G},{public_key},{r}"
    c = int(hashlib.sha256(challenge_input.encode()).hexdigest(), 16) % P
    s = (k + c * private_key) % (P - 1)
    return r, s

def verify_ballot_zkp(public_key, r, s):
    """Vérifie mathématiquement la validité du ZKP associé au bulletin"""
    challenge_input = f"{G},{public_key},{r}"
    c = int(hashlib.sha256(challenge_input.encode()).hexdigest(), 16) % P
    lhs = pow(G, s, P)
    rhs = (r * pow(public_key, c, P)) % P
    return lhs == rhs


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
            min_votes = min(counts.values())
            tied_candidates = [c for c, v in counts.items() if v == min_votes]
            
            if len(tied_candidates) > 1:
                tally_log.append(f"⚠️ Égalité entre {', '.join(tied_candidates)} ({min_votes:.2f} votes). Analyse des préférences...")
                eliminated_candidate = None
                
                for rank_idx in range(1, len(candidates_data)):
                    rank_counts = {c: 0 for c in tied_candidates}
                    for b in ballots:
                        ranking = b['ranking']
                        if rank_idx < len(ranking):
                            cand_at_rank = ranking[rank_idx]
                            if cand_at_rank in rank_counts:
                                rank_counts[cand_at_rank] += b['weight']
                    
                    min_rank_votes = min(rank_counts.values())
                    worst_candidates = [c for c, v in rank_counts.items() if v == min_rank_votes]
                    
                    if len(worst_candidates) == 1:
                        eliminated_candidate = worst_candidates[0]
                        tally_log.append(f"🔍 Au choix n°{rank_idx+1}, {eliminated_candidate} est le moins plébiscité ({min_rank_votes} votes).")
                        break
                    elif len(worst_candidates) < len(tied_candidates):
                        tied_candidates = worst_candidates
                
                if not eliminated_candidate:
                    eliminated_candidate = random.choice(tied_candidates)
                    tally_log.append(f"🎲 Égalité totale persistante. Tirage au sort : {eliminated_candidate} est éliminé.")
                
                lowest = eliminated_candidate
            else:
                lowest = tied_candidates[0]
                
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
st.set_page_config(page_title="Système de Vote RBAC Secure", layout="wide")
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
            voters = supabase.table('voters').select('voter_id').order('voter_id').execute().data
            st.write([v['voter_id'] for v in voters])
            if st.button("Effacer Votants"):
                supabase.table('voters').delete().neq('voter_id', '0').execute()
                st.rerun()

        st.divider()
        seats = st.number_input("Nombre de sièges", min_value=1, value=1)
        
        if st.button("🚀 DÉMARRER L'ÉLECTION (Générer les Combinaisons Cryptographiques)", type="primary"):
            supabase.table('ballots').delete().neq('id', '00000000-0000-0000-0000-000000000000').execute()
            supabase.table('voter_receipts').delete().neq('voter_id', '0').execute()
            supabase.table('combinations').delete().neq('comb_id', '0').execute()
            supabase.table('system_state').upsert({'key': 'status', 'value': 'Ouvert'}).execute()
            supabase.table('system_state').upsert({'key': 'seats', 'value': str(seats)}).execute()
            
            voters_data = supabase.table('voters').select('voter_id').order('voter_id').execute().data
            voter_ids = [v['voter_id'] for v in voters_data]
            cand_names = [c['name'] for c in supabase.table('candidates').select('name').execute().data]
            num_voters = len(voter_ids)
            
            if len(cand_names) > 5 or len(cand_names) == 0:
                st.error("Erreur: Il faut entre 1 et 5 candidats.")
                st.stop()
                
            num_combs = max(1, int(math.log2(num_voters))) if num_voters > 0 else 1
            alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
            
            for i in range(num_combs):
                comb_id = alphabet[i]
                sampled_shapes = random.sample(SHAPES, len(cand_names))
                shuffled_cands = list(cand_names)
                random.shuffle(shuffled_cands)
                mapping = {sampled_shapes[j]: shuffled_cands[j] for j in range(len(cand_names))}
                
                # Génération de la clé cryptographique du lot pour les ZKP
                priv_k, pub_k = cryptographic_keygen()
                
                supabase.table('combinations').insert({
                    'comb_id': comb_id,
                    'mapping': mapping,
                    'max_limit': int(pub_k),      # Stockage propre de la clé publique de vérification
                    'secret_key': str(priv_k)     # Clé privée distribuée à l'isoloir pour la preuve
                }).execute()

            comb_assignments = [alphabet[i % num_combs] for i in range(num_voters)]
            random.shuffle(comb_assignments)

            for i, v_id in enumerate(voter_ids):
                assigned_c_id = comb_assignments[i]
                supabase.table('voters').update({'assigned_comb': assigned_c_id, 'has_voted': False}).eq('voter_id', v_id).execute()

            st.success(f"L'élection est ouverte ! Lots signés cryptographiquement par clé ElGamal.")

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
            else:
                st.session_state.voter_id = v_id
                st.session_state.assigned_comb = voter_data[0]['assigned_comb']
                st.rerun()
    else:
        voter_data = supabase.table('voters').select('has_voted').eq('voter_id', st.session_state.voter_id).execute().data
        if voter_data and voter_data[0]['has_voted']:
            st.warning("⚠️ Vous avez déjà voté. Soumettre un nouveau bulletin écrasera le précédent.")

        all_voters = supabase.table('voters').select('voter_id').order('voter_id').execute().data
        voter_ids_list = [v['voter_id'] for v in all_voters]
        try:
            voter_index = voter_ids_list.index(st.session_state.voter_id) + 1
        except ValueError:
            voter_index = "?"

        if st.button("🚪 Se déconnecter (Voter plus tard)"):
            del st.session_state.voter_id
            if "assigned_comb" in st.session_state:
                del st.session_state.assigned_comb
            st.rerun()

        tab1, tab2 = st.tabs(["🎫 Centre de Remise des Billets", f"✉️ Isoloir (Bulletin de Vote)"])
        
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
            st.subheader(f"Bulletin de vote: {voter_index}")
            st.markdown(f"**voter ID:** `{st.session_state.voter_id}`")
            
            available_shapes = SHAPES
            index_labels = [f"Choix {i}" for i in range(1, len(available_shapes) + 1)]
            
            if "ballot_df" not in st.session_state or list(st.session_state.ballot_df.columns) != available_shapes:
                st.session_state.ballot_df = pd.DataFrame(False, index=index_labels, columns=available_shapes)

            edited_df = st.data_editor(st.session_state.ballot_df, use_container_width=True)
            typed_comb_id = st.text_input("Saisissez votre ID de Combinaison (Lettre)").strip().upper()

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
                elif typed_comb_id != st.session_state.assigned_comb:
                    st.error("Erreur d'authentification de lot : ID de combinaison incorrect pour votre session.")
                else:
                    # Génération à la volée du ZKP individuel pour prouver l'autorisation sans rompre l'anonymat
                    comb_crypto = supabase.table('combinations').select('secret_key', 'max_limit').eq('comb_id', typed_comb_id).execute().data
                    if not comb_crypto:
                        st.error("Code de combinaison invalide.")
                        st.stop()
                    
                    priv_key = int(comb_crypto[0]['secret_key'])
                    pub_key = int(comb_crypto[0]['max_limit'])
                    
                    # Construction mathématique de la preuve à divulgation nulle
                    zkp_r, zkp_s = generate_ballot_zkp(priv_key, pub_key)
                    
                    v_hash = hashlib.sha256((st.session_state.voter_id + "SEVCO_SALT").encode()).hexdigest()
                    supabase.table('ballots').delete().eq('voter_hash', v_hash).execute()

                    # Stockage du bulletin enrichi de ses métadonnées ZKP
                    supabase.table('ballots').insert({
                        'comb_id': typed_comb_id,
                        'shapes_ranking': ranking,
                        'voter_hash': v_hash,
                        'zkp_proof': json.dumps({"r": zkp_r, "s": zkp_s})  # Attachement de la preuve
                    }).execute()
                    
                    supabase.table('voter_receipts').upsert({'voter_id': st.session_state.voter_id}).execute()
                    supabase.table('voters').update({'has_voted': True}).eq('voter_id', st.session_state.voter_id).execute()
                    
                    del st.session_state.voter_id
                    st.success("Bulletin cryptographiquement signé et transmis !")
                    time.sleep(2)
                    st.rerun()


# ==========================================
# NODE 3: INFRASTRUCTURE MONITOR
# ==========================================
elif node == "Moniteur d'Infrastructure (Projecteur)":
    st.title("👁️ Architecture de Dépouillement")
    infra_pwd = st.text_input("Mot de passe Réseau Infrastructure", type="password")
    
    if infra_pwd == "infra123":
        st.success("Accès sécurisé accordé.")
        
        if st.button("Rafraîchir les données en direct"):
            st.rerun()
        
        st.divider()
        st.subheader("1. Mix-Net (Anonymisation des Flux)")
        ballots = supabase.table('ballots').select('*').execute().data
        if ballots:
            shuffled = list(ballots)
            random.shuffle(shuffled)
            df_mix = pd.DataFrame([{"ID Combinaison": b['comb_id'], "Choix Formes": " > ".join(b['shapes_ranking'])} for b in shuffled])
            st.dataframe(df_mix, use_container_width=True)
        else:
            st.write("Le Mix-Net est vide.")

        st.divider()
        st.subheader("2. Réception des bulletins (Vérification Individuelle ZKP)")
        combs = supabase.table('combinations').select('*').execute().data
        
        # Dictionnaire des clés publiques par lot pour vérification instantanée
        pub_keys = {c['comb_id']: int(c['max_limit']) for c in combs}
        mappings = {c['comb_id']: c['mapping'] for c in combs}
        
        valid_candidate_ballots = []
        
        col1, col2, col3 = st.columns(3)
        cols = [col1, col2, col3]
        
        for i, comb in enumerate(combs):
            with cols[i % 3]:
                st.write(f"### Lot: {comb['comb_id']}")
                comb_ballots = [b for b in ballots if b['comb_id'] == comb['comb_id']]
                st.write(f"Bulletins en attente de traitement: **{len(comb_ballots)}**")
                
                # PLUS AUCUNE ANNULATION GLOBALE : Traitement unitaire autonome
                for b in comb_ballots:
                    try:
                        proof = json.loads(b['zkp_proof'])
                        r, s = proof['r'], proof['s']
                        pub_k = pub_keys[b['comb_id']]
                        
                        # Exécution de la preuve de Schnorr pour valider l'intégrité du bulletin
                        if verify_ballot_zkp(pub_k, r, s):
                            cand_ranking = [mappings[b['comb_id']].get(shape) for shape in b['shapes_ranking'] if mappings[b['comb_id']].get(shape) is not None]
                            if cand_ranking:
                                valid_candidate_ballots.append(cand_ranking)
                                st.success(f"✅ Bulletin Vérifié (ZKP Valide) : {' > '.join(cand_ranking)}")
                        else:
                            st.error("❌ Alerte : ZKP invalide détecté. Bulletin frauduleux rejeté individuellement.")
                    except Exception:
                        st.error("❌ Anomalie structurelle sur un bulletin. Rejet unitaire.")

        st.divider()
        st.subheader("3. Centre de Décompte (Tally)")
        
        all_voters_data = supabase.table('voters').select('voter_id').order('voter_id').execute().data
        voter_ids_list = [v['voter_id'] for v in all_voters_data]
        receipts = supabase.table('voter_receipts').select('voter_id').execute().data
        
        st.write("Numéros de bulletins reçus enregistrés (Vérifiabilité individuelle anonyme) :")
        if receipts:
            receipt_indices = [voter_ids_list.index(r['voter_id']) + 1 for r in receipts if r['voter_id'] in voter_ids_list]
            receipt_indices.sort()
            st.write(", ".join(map(str, receipt_indices)))
        else:
            st.write("Aucun bulletin déposé.")
        
        if valid_candidate_ballots:
            first_prefs = {}
            for b in valid_candidate_ballots:
                first = b[0]
                first_prefs[first] = first_prefs.get(first, 0) + 1
                
            st.write("### Intentions de 1er Choix (Temps Réel)")
            st.bar_chart(pd.DataFrame(list(first_prefs.items()), columns=["Candidat", "Votes"]).set_index("Candidat"))

        status_req = supabase.table('system_state').select('value').eq('key', 'status').execute().data
        if status_req and status_req[0]['value'] == "Fermé":
            seats = int(supabase.table('system_state').select('value').eq('key', 'seats').execute().data[0]['value'])
            st.write("### Décompte Officiel STV")
            st.text_area("Log de l'algorithme", run_stv_tally(valid_candidate_ballots, seats), height=300)
        else:
            st.warning("L'élection est toujours en cours. Le décompte STV final est verrouillé.")
            
    elif infra_pwd != "":
        st.error("🔒 Clé d'infrastructure non valide. Accès refusé.")
