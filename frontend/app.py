"""Tela do MediFlow (Streamlit): envio de documentos e painel de revisão humana."""
import os
import uuid

import requests
import streamlit as st

API_URL = os.getenv("MEDIFLOW_API_URL", "http://127.0.0.1:8000")

st.set_page_config(page_title="MediFlow", page_icon="🏥", layout="wide")

DESTINOS = {
    "Fila_Emergencia_Medica": ("🚨 Fila de Emergência Médica", "error"),
    "Fila_Revisao_Humana": ("🔎 Fila de Revisão Humana", "warning"),
    "Farmacia_Hospitalar": ("💊 Farmácia Hospitalar", "success"),
    "Auditoria_Autorizacoes": ("📋 Auditoria de Autorizações", "success"),
    "Prontuario_Eletronico_Paciente": ("🗂️ Prontuário Eletrônico do Paciente", "success"),
}


def chamar_api(metodo: str, rota: str, **kwargs):
    """Chama a API do MediFlow e mostra um aviso amigável se algo der errado."""
    try:
        resposta = requests.request(metodo, f"{API_URL}{rota}", timeout=180, **kwargs)
        resposta.raise_for_status()
        return resposta.json()
    except requests.RequestException as erro:
        st.error(f"Não foi possível falar com a API ({erro}). Ela está ligada?")
        return None


def mostrar_resultado(r: dict) -> None:
    """Exibe a triagem de forma visual."""
    c = r["classificacao"]
    d = r["dados_extraidos"]
    dec = r["decisao_roteamento"]

    rotulo, estilo = DESTINOS.get(dec["destino_principal"], (dec["destino_principal"], "info"))
    getattr(st, estilo)(f"**Destino: {rotulo}**  \n{dec['justificativa_roteamento']}")

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Tipo de documento", c["tipo_documento"])
    col2.metric("Prioridade", c["nivel_prioridade"])
    col3.metric("Confiança da classificação", f"{c['score_confianca_classificacao']:.0%}")
    col4.metric("Confiança da extração", f"{r['score_confianca_extracao']:.0%}")

    if dec.get("notificacao_gerada"):
        n = dec["notificacao_gerada"]
        st.info(f"📣 **{n['canal']}**: {n['mensagem']}")
    if dec.get("destinos_secundarios"):
        nomes = [DESTINOS.get(x, (x,))[0] for x in dec["destinos_secundarios"]]
        st.caption("Também enviado para: " + ", ".join(nomes))

    st.subheader("Dados extraídos")
    esquerda, direita = st.columns(2)
    p = d["paciente"]
    m = d["medico_solicitante"]
    esquerda.markdown(
        f"**Paciente:** {p.get('nome') or 'não informado'}  \n"
        f"**Idade:** {p.get('idade') or 'não informada'}  \n"
        f"**Médico:** {m.get('nome') or 'não informado'}  \n"
        f"**CRM:** {m.get('crm') or 'não informado'}"
    )
    direita.markdown(
        f"**Diagnóstico:** {d.get('diagnostico_principal') or 'não informado'}  \n"
        f"**CID-10:** {d.get('cid_sugerido') or 'não informado'}  \n"
        f"**Exame:** {d.get('exame_realizado') or 'não se aplica'}  \n"
        f"**Resultado do exame:** {d.get('resultado_exame')}"
    )

    if d.get("medicamentos"):
        st.markdown("**Medicamentos**")
        st.dataframe(d["medicamentos"], hide_index=True)
    if d.get("exames_solicitados"):
        st.markdown("**Exames solicitados:** " + ", ".join(d["exames_solicitados"]))
    if d.get("campos_ilegiveis_ou_ausentes"):
        st.warning("Campos ilegíveis ou ausentes: " + ", ".join(d["campos_ilegiveis_ou_ausentes"]))

    oci = r.get("armazenamento_oci")
    if oci:
        st.caption(f"☁️ OCI Object Storage: {oci['bucket']}/{oci['caminho_objeto']} ({oci['status_backup']})")
    with st.expander("Ver JSON completo"):
        st.json(r)


# ---------- Barra lateral ----------

with st.sidebar:
    st.title("🏥 MediFlow")
    st.markdown("*A informação existe. O MediFlow faz ela chegar.*")
    st.caption("Triagem, extração e roteamento de documentos clínicos com IA.")
    try:
        requests.get(API_URL, timeout=5).raise_for_status()
        st.success("API online")
    except requests.RequestException:
        st.error("API offline. Ligue o backend.")
    st.caption("Use apenas dados fictícios (LGPD).")

aba_triagem, aba_revisao = st.tabs(["📄 Nova triagem", "🔎 Revisão humana"])

# ---------- Aba 1: nova triagem ----------

with aba_triagem:
    forma = st.radio("Como enviar o documento?", ["Arquivo (PDF ou imagem)", "Texto"], horizontal=True)
    canal = st.selectbox(
        "Canal de origem",
        ["Pronto_Socorro", "Ambulatorio", "Internacao", "Laboratorio", "Farmacia", "Recepcao"],
    )

    arquivo = None
    texto = None
    if forma.startswith("Arquivo"):
        arquivo = st.file_uploader("Documento", type=["pdf", "jpg", "jpeg", "png", "webp"])
    else:
        texto = st.text_area("Texto do documento", height=200)

    if st.button("Processar documento", type="primary"):
        if not arquivo and not (texto and texto.strip()):
            st.warning("Envie um arquivo ou cole o texto do documento.")
        else:
            with st.spinner("O agente está lendo e classificando o documento..."):
                if arquivo:
                    resultado = chamar_api(
                        "POST",
                        "/triagem/arquivo",
                        files={"arquivo": (arquivo.name, arquivo.getvalue(), arquivo.type)},
                        data={"canal_origem": canal},
                    )
                else:
                    resultado = chamar_api(
                        "POST",
                        "/triagem",
                        json={
                            "documento_id": f"DOC-{uuid.uuid4().hex[:8].upper()}",
                            "tipo_arquivo": "TEXTO",
                            "documento_texto": texto,
                            "canal_origem": canal,
                        },
                    )
            if resultado:
                st.session_state["resultado"] = resultado

    if "resultado" in st.session_state:
        st.divider()
        mostrar_resultado(st.session_state["resultado"])

# ---------- Aba 2: revisão humana ----------

with aba_revisao:
    st.markdown("Documentos com baixa confiança, dados faltando ou ilegíveis aguardam a decisão de um auditor.")
    if st.button("🔄 Atualizar lista"):
        st.rerun()

    lista = chamar_api("GET", "/auditoria")
    pendentes = lista["pendentes"] if lista else []

    if not pendentes:
        st.success("Nenhum documento aguardando revisão.")
    else:
        escolhido = st.selectbox(
            f"{len(pendentes)} documento(s) pendente(s)",
            pendentes,
            format_func=lambda caminho: caminho.split("/")[-1].removesuffix(".json"),
        )
        doc = chamar_api("GET", f"/documentos/{escolhido}")
        if doc:
            mostrar_resultado(doc)
            st.subheader("Decisão do auditor")
            auditor = st.text_input("Nome do auditor")
            observacao = st.text_area("Observação", placeholder="Ex.: CRM confirmado por telefone com a clínica.")

            botao_aprovar, botao_rejeitar = st.columns(2)
            for coluna, aprovado, rotulo in (
                (botao_aprovar, True, "✅ Aprovar extração"),
                (botao_rejeitar, False, "❌ Rejeitar extração"),
            ):
                if coluna.button(rotulo):
                    ok = chamar_api(
                        "POST",
                        f"/auditoria/{doc['documento_id']}/decisao",
                        json={"aprovado": aprovado, "auditor": auditor or "auditor", "observacao": observacao or None},
                    )
                    if ok:
                        st.toast("Decisão registrada no OCI.")
                        st.rerun()