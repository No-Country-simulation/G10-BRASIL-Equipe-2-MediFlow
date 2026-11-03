"""Modelos de dados do MediFlow, validados com Pydantic."""
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


# ---------- Listas de valores permitidos ----------

class TipoArquivo(str, Enum):
    PDF = "PDF"
    IMAGEM = "IMAGEM"
    TEXTO = "TEXTO"


class TipoDocumento(str, Enum):
    RECEITA = "Receituário Médico"
    LAUDO_LABORATORIAL = "Laudo de Exame Laboratorial"
    LAUDO_IMAGEM = "Laudo de Exame de Imagem"
    GUIA = "Guia de Solicitação de Procedimento"
    ALTA = "Relatório de Alta/Internação"
    ATESTADO = "Atestado Médico"
    DESCONHECIDO = "Desconhecido"


class NivelPrioridade(str, Enum):
    ROTINA = "Rotina"
    ATENCAO = "Atenção"
    URGENTE = "Urgente"


class ResultadoExame(str, Enum):
    NORMAL = "Normal"
    ALTERADO = "Alterado"
    CRITICO = "Crítico"
    NAO_SE_APLICA = "Não se aplica"


class Destino(str, Enum):
    URGENCIA = "Fila_Emergencia_Medica"
    AUDITORIA_AUTORIZACOES = "Auditoria_Autorizacoes"
    FARMACIA = "Farmacia_Hospitalar"
    PRONTUARIO = "Prontuario_Eletronico_Paciente"
    REVISAO_HUMANA = "Fila_Revisao_Humana"


# ---------- Entrada ----------

class DocumentoEntrada(BaseModel):
    documento_id: str
    tipo_arquivo: TipoArquivo = TipoArquivo.TEXTO
    documento_texto: Optional[str] = None
    canal_origem: Optional[str] = None


# ---------- Dados extraídos ----------

class Paciente(BaseModel):
    nome: Optional[str] = None
    idade: Optional[int] = None
    identificador: Optional[str] = None


class Medico(BaseModel):
    nome: Optional[str] = None
    crm: Optional[str] = None


class Medicamento(BaseModel):
    nome: str
    dosagem: Optional[str] = None
    posologia: Optional[str] = None
    controlado: bool = False


class Classificacao(BaseModel):
    tipo_documento: TipoDocumento
    especialidade: Optional[str] = None
    nivel_prioridade: NivelPrioridade = NivelPrioridade.ROTINA
    score_confianca_classificacao: float = Field(ge=0, le=1)


class DadosExtraidos(BaseModel):
    paciente: Paciente = Paciente()
    medico_solicitante: Medico = Medico()
    exame_realizado: Optional[str] = None
    exames_solicitados: List[str] = []
    resultado_exame: ResultadoExame = ResultadoExame.NAO_SE_APLICA
    diagnostico_principal: Optional[str] = None
    cid_sugerido: Optional[str] = None
    medicamentos: List[Medicamento] = []
    campos_ilegiveis_ou_ausentes: List[str] = []


# ---------- Decisão e saída ----------

class Notificacao(BaseModel):
    canal: str
    mensagem: str


class DecisaoRoteamento(BaseModel):
    destino_principal: Destino
    destinos_secundarios: List[Destino] = []
    requer_auditoria_humana: bool = False
    justificativa_roteamento: str
    notificacao_gerada: Optional[Notificacao] = None


class ArmazenamentoOCI(BaseModel):
    bucket: str
    caminho_objeto: str
    status_backup: str


class RespostaTriagem(BaseModel):
    status: str = "processado"
    documento_id: str
    classificacao: Classificacao
    dados_extraidos: DadosExtraidos
    score_confianca_extracao: float = Field(ge=0, le=1)
    decisao_roteamento: DecisaoRoteamento
    armazenamento_oci: Optional[ArmazenamentoOCI] = None