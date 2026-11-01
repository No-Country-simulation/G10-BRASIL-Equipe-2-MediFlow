"""Persistência no OCI Object Storage usando o link pré-autenticado (PAR)."""
import os
import re
import unicodedata
from typing import List
from urllib.parse import quote

import requests
from dotenv import load_dotenv

from app.schemas import ArmazenamentoOCI, Destino, RespostaTriagem

load_dotenv()

PAR_URL = os.getenv("OCI_PAR_URL", "")
BUCKET = os.getenv("OCI_BUCKET", "mediflow-documentos-clinicos")

PASTAS_POR_DESTINO = {
    Destino.URGENCIA: "processados/urgentes",
    Destino.FARMACIA: "processados/farmacia",
    Destino.AUDITORIA_AUTORIZACOES: "processados/auditoria_autorizacoes",
    Destino.PRONTUARIO: "processados/prontuario",
    Destino.REVISAO_HUMANA: "auditoria_humana",
}


def _url(caminho: str) -> str:
    if not PAR_URL:
        raise RuntimeError("OCI_PAR_URL não configurada no .env")
    return PAR_URL.rstrip("/") + "/" + quote(caminho)


def _enviar(caminho: str, conteudo: bytes, tipo: str) -> None:
    resposta = requests.put(_url(caminho), data=conteudo, headers={"Content-Type": tipo}, timeout=30)
    resposta.raise_for_status()


def _slug(texto: str) -> str:
    """Transforma 'José da Silva' em 'jose-da-silva' para usar como nome de pasta."""
    sem_acento = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-zA-Z0-9]+", "-", sem_acento).strip("-").lower()


def salvar_original(documento_id: str, conteudo: bytes, extensao: str, tipo: str) -> str:
    """Guarda o documento como chegou, na pasta recebidos/."""
    caminho = f"recebidos/{documento_id}.{extensao}"
    _enviar(caminho, conteudo, tipo)
    return caminho


def salvar_resultado(resposta: RespostaTriagem) -> RespostaTriagem:
    """Salva o JSON da triagem na pasta do destino e na pasta do paciente."""
    pasta = PASTAS_POR_DESTINO[resposta.decisao_roteamento.destino_principal]
    caminho = f"{pasta}/{resposta.documento_id}.json"
    resposta.armazenamento_oci = ArmazenamentoOCI(bucket=BUCKET, caminho_objeto=caminho, status_backup="sucesso")

    try:
        conteudo = resposta.model_dump_json(indent=2).encode("utf-8")
        _enviar(caminho, conteudo, "application/json")

        nome = resposta.dados_extraidos.paciente.nome
        if nome and pasta != "auditoria_humana":
            _enviar(f"pacientes/{_slug(nome)}/{resposta.documento_id}.json", conteudo, "application/json")
    except Exception as erro:  # a triagem não pode parar por falha no armazenamento
        resposta.armazenamento_oci.status_backup = f"falha: {erro}"

    return resposta


def listar(prefixo: str = "") -> List[str]:
    """Lista os arquivos de uma pasta do bucket (usado no painel de auditoria)."""
    resposta = requests.get(PAR_URL, params={"prefix": prefixo}, timeout=30)
    resposta.raise_for_status()
    return [objeto["name"] for objeto in resposta.json().get("objects", [])]


def ler_json(caminho: str) -> dict:
    resposta = requests.get(_url(caminho), timeout=30)
    resposta.raise_for_status()
    return resposta.json()