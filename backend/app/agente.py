"""Grafo de decisão do MediFlow (LangGraph): extrai, valida e roteia o documento."""
from typing import List, Optional, TypedDict

from langgraph.graph import END, START, StateGraph

from app.extrator import ResultadoExtracao, extrair
from app.schemas import (
    Classificacao,
    DadosExtraidos,
    DecisaoRoteamento,
    Destino,
    NivelPrioridade,
    Notificacao,
    RespostaTriagem,
    ResultadoExame,
    TipoDocumento,
)

# Abaixo deste valor, a leitura é considerada duvidosa e vai para revisão humana.
LIMITE_CONFIANCA = 0.75

# Campos que precisam existir em cada tipo de documento.
CAMPOS_OBRIGATORIOS = {
    TipoDocumento.RECEITA: ["paciente", "crm", "medicamentos"],
    TipoDocumento.LAUDO_LABORATORIAL: ["paciente", "resultado"],
    TipoDocumento.LAUDO_IMAGEM: ["paciente", "resultado"],
    TipoDocumento.GUIA: ["paciente", "crm", "exames_solicitados"],
    TipoDocumento.ALTA: ["paciente"],
    TipoDocumento.ATESTADO: ["paciente", "crm"],
}


class EstadoTriagem(TypedDict, total=False):
    documento_id: str
    canal_origem: Optional[str]
    texto: Optional[str]
    arquivo: Optional[bytes]
    mime_type: Optional[str]
    extracao: Optional[ResultadoExtracao]
    erro: Optional[str]
    problemas: List[str]
    decisao: Optional[DecisaoRoteamento]


# ---------- Funções de apoio ----------

def _nome_paciente(ext: ResultadoExtracao) -> str:
    return ext.dados_extraidos.paciente.nome or "paciente não identificado"


def _campo_presente(campo: str, dados: DadosExtraidos) -> bool:
    if campo == "paciente":
        return bool(dados.paciente.nome)
    if campo == "crm":
        return bool(dados.medico_solicitante.crm)
    if campo == "medicamentos":
        return bool(dados.medicamentos)
    if campo == "exames_solicitados":
        return bool(dados.exames_solicitados)
    if campo == "resultado":
        return dados.resultado_exame != ResultadoExame.NAO_SE_APLICA
    return True


def _eh_urgente(ext: ResultadoExtracao) -> bool:
    return (
        ext.classificacao.nivel_prioridade == NivelPrioridade.URGENTE
        or ext.dados_extraidos.resultado_exame == ResultadoExame.CRITICO
    )


# ---------- Nós do grafo ----------

def no_extrair(estado: EstadoTriagem) -> dict:
    try:
        resultado = extrair(
            texto=estado.get("texto"),
            arquivo=estado.get("arquivo"),
            mime_type=estado.get("mime_type"),
        )
        return {"extracao": resultado, "erro": None}
    except Exception as erro:  # se a leitura falhar, o documento vai para revisão humana
        return {"extracao": None, "erro": f"Falha na leitura do documento: {erro}"}


def no_validar(estado: EstadoTriagem) -> dict:
    if estado.get("erro"):
        return {"problemas": [estado["erro"]]}

    ext = estado["extracao"]
    tipo = ext.classificacao.tipo_documento
    problemas = []

    if tipo == TipoDocumento.DESCONHECIDO:
        problemas.append("Tipo de documento não identificado.")

    confianca = min(ext.classificacao.score_confianca_classificacao, ext.score_confianca_extracao)
    if confianca < LIMITE_CONFIANCA:
        problemas.append(f"Confiança da leitura baixa ({confianca:.2f}).")

    for campo in CAMPOS_OBRIGATORIOS.get(tipo, []):
        if not _campo_presente(campo, ext.dados_extraidos):
            problemas.append(f"Campo obrigatório ausente ou ilegível: {campo}.")

    return {"problemas": problemas}


def decidir_caminho(estado: EstadoTriagem) -> str:
    """Nó condicional: escolhe para onde o documento segue."""
    ext = estado.get("extracao")
    if ext and _eh_urgente(ext):
        return "urgencia"  # urgência nunca espera, mesmo com dúvidas
    if estado.get("problemas"):
        return "revisao_humana"
    tipo = ext.classificacao.tipo_documento
    if tipo == TipoDocumento.RECEITA:
        return "farmacia"
    if tipo == TipoDocumento.GUIA:
        return "auditoria"
    return "prontuario"


def no_urgencia(estado: EstadoTriagem) -> dict:
    ext = estado["extracao"]
    problemas = estado.get("problemas", [])
    achado = ext.dados_extraidos.diagnostico_principal or ext.classificacao.tipo_documento.value
    origem = estado.get("canal_origem") or "unidade de origem"
    justificativa = f"Achado crítico ou pedido de urgência: {achado}."
    if problemas:
        justificativa += " Dados pendentes enviados também para revisão humana."
    decisao = DecisaoRoteamento(
        destino_principal=Destino.URGENCIA,
        destinos_secundarios=[Destino.PRONTUARIO] + ([Destino.REVISAO_HUMANA] if problemas else []),
        requer_auditoria_humana=bool(problemas),
        justificativa_roteamento=justificativa,
        notificacao_gerada=Notificacao(
            canal="Alerta_Plantao_Medico",
            mensagem=f"ALERTA URGENTE: {achado} para {_nome_paciente(ext)} ({origem}).",
        ),
    )
    return {"decisao": decisao}


def no_revisao_humana(estado: EstadoTriagem) -> dict:
    problemas = estado.get("problemas", [])
    decisao = DecisaoRoteamento(
        destino_principal=Destino.REVISAO_HUMANA,
        requer_auditoria_humana=True,
        justificativa_roteamento=" ".join(problemas) or "Documento ambíguo.",
        notificacao_gerada=Notificacao(
            canal="Fila_Auditoria_Clinica",
            mensagem=f"Documento {estado['documento_id']} aguarda revisão humana.",
        ),
    )
    return {"decisao": decisao}


def no_farmacia(estado: EstadoTriagem) -> dict:
    ext = estado["extracao"]
    controlados = [m.nome for m in ext.dados_extraidos.medicamentos if m.controlado]
    notificacao = None
    justificativa = "Receita válida encaminhada para dispensação."
    if controlados:
        justificativa += " Contém medicamento controlado."
        notificacao = Notificacao(
            canal="Alerta_Farmaceutico",
            mensagem=(
                f"Receita com medicamento controlado ({', '.join(controlados)}) "
                f"para {_nome_paciente(ext)}. Conferir antes de dispensar."
            ),
        )
    decisao = DecisaoRoteamento(
        destino_principal=Destino.FARMACIA,
        destinos_secundarios=[Destino.PRONTUARIO],
        justificativa_roteamento=justificativa,
        notificacao_gerada=notificacao,
    )
    return {"decisao": decisao}


def no_auditoria(estado: EstadoTriagem) -> dict:
    ext = estado["extracao"]
    exames = ", ".join(ext.dados_extraidos.exames_solicitados)
    decisao = DecisaoRoteamento(
        destino_principal=Destino.AUDITORIA_AUTORIZACOES,
        destinos_secundarios=[Destino.PRONTUARIO],
        justificativa_roteamento=f"Guia encaminhada para autorização: {exames}.",
    )
    return {"decisao": decisao}


def no_prontuario(estado: EstadoTriagem) -> dict:
    ext = estado["extracao"]
    dados = ext.dados_extraidos
    tipo = ext.classificacao.tipo_documento
    secundarios = []
    notificacao = None
    justificativa = f"{tipo.value} registrado no prontuário do paciente."

    if dados.resultado_exame == ResultadoExame.ALTERADO:
        medico = dados.medico_solicitante.nome or "médico solicitante"
        justificativa += " Resultado alterado: médico solicitante notificado."
        notificacao = Notificacao(
            canal="Alerta_Medico_Solicitante",
            mensagem=(
                f"Para {medico}: resultado alterado em {dados.exame_realizado or 'exame'} "
                f"de {_nome_paciente(ext)}. Avaliar antecipar o retorno."
            ),
        )

    if tipo == TipoDocumento.ALTA and dados.medicamentos:
        secundarios.append(Destino.FARMACIA)
        justificativa += " Medicamentos de alta enviados à farmácia."

    decisao = DecisaoRoteamento(
        destino_principal=Destino.PRONTUARIO,
        destinos_secundarios=secundarios,
        justificativa_roteamento=justificativa,
        notificacao_gerada=notificacao,
    )
    return {"decisao": decisao}


# ---------- Montagem do grafo ----------

DESTINOS = ["urgencia", "revisao_humana", "farmacia", "auditoria", "prontuario"]


def _montar_grafo():
    grafo = StateGraph(EstadoTriagem)
    grafo.add_node("extrair", no_extrair)
    grafo.add_node("validar", no_validar)
    grafo.add_node("urgencia", no_urgencia)
    grafo.add_node("revisao_humana", no_revisao_humana)
    grafo.add_node("farmacia", no_farmacia)
    grafo.add_node("auditoria", no_auditoria)
    grafo.add_node("prontuario", no_prontuario)

    grafo.add_edge(START, "extrair")
    grafo.add_edge("extrair", "validar")
    grafo.add_conditional_edges("validar", decidir_caminho, DESTINOS)
    for destino in DESTINOS:
        grafo.add_edge(destino, END)
    return grafo.compile()


AGENTE = _montar_grafo()


def processar(
    documento_id: str,
    texto: Optional[str] = None,
    arquivo: Optional[bytes] = None,
    mime_type: Optional[str] = None,
    canal_origem: Optional[str] = None,
) -> RespostaTriagem:
    """Roda o documento pelo grafo e devolve a resposta no formato do enunciado."""
    estado = AGENTE.invoke({
        "documento_id": documento_id,
        "canal_origem": canal_origem,
        "texto": texto,
        "arquivo": arquivo,
        "mime_type": mime_type,
    })

    ext = estado.get("extracao")
    if ext is None:
        classificacao = Classificacao(
            tipo_documento=TipoDocumento.DESCONHECIDO,
            score_confianca_classificacao=0,
        )
        dados = DadosExtraidos()
        score = 0.0
    else:
        classificacao = ext.classificacao
        dados = ext.dados_extraidos
        score = ext.score_confianca_extracao

    decisao = estado["decisao"]
    em_revisao = decisao.destino_principal == Destino.REVISAO_HUMANA
    return RespostaTriagem(
        status="aguardando_revisao_humana" if em_revisao else "processado",
        documento_id=documento_id,
        classificacao=classificacao,
        dados_extraidos=dados,
        score_confianca_extracao=score,
        decisao_roteamento=decisao,
    )