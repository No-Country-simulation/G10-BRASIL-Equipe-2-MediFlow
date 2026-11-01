"""API REST do MediFlow (FastAPI). Documentação interativa em /docs."""
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from app.agente import processar
from app.armazenamento import (
    ler_json,
    listar,
    salvar_original,
    salvar_resultado,
    salvar_revisao,
)
from app.schemas import DocumentoEntrada, RespostaTriagem

app = FastAPI(
    title="MediFlow API",
    description="Agente autônomo para triagem, extração e roteamento de documentos clínicos.",
    version="1.1.0",
)

TIPOS_ACEITOS = {
    "application/pdf": "pdf",
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
}


class DecisaoAuditor(BaseModel):
    aprovado: bool
    auditor: str = "auditor"
    observacao: Optional[str] = None


def _novo_id() -> str:
    return f"DOC-{uuid.uuid4().hex[:8].upper()}"


def _id_do_caminho(caminho: str) -> str:
    """'auditoria_humana/DOC-123.json' vira 'DOC-123'."""
    return caminho.rsplit("/", 1)[-1].removesuffix(".json")


def _guardar_original(documento_id: str, conteudo: bytes, extensao: str, tipo: str) -> None:
    """Salva o original no bucket sem interromper a triagem se a nuvem falhar."""
    try:
        salvar_original(documento_id, conteudo, extensao, tipo)
    except Exception as erro:
        print(f"Aviso: não foi possível salvar o original de {documento_id}: {erro}")


@app.get("/", tags=["Status"])
def status():
    return {"servico": "MediFlow", "status": "online"}


@app.post("/triagem", response_model=RespostaTriagem, tags=["Triagem"])
def triagem_texto(documento: DocumentoEntrada):
    """Recebe o documento em texto (formato JSON do enunciado) e devolve a triagem."""
    if not documento.documento_texto:
        raise HTTPException(status_code=400, detail="Envie o campo documento_texto.")

    _guardar_original(
        documento.documento_id,
        documento.model_dump_json(indent=2).encode("utf-8"),
        "json",
        "application/json",
    )
    resposta = processar(
        documento_id=documento.documento_id,
        texto=documento.documento_texto,
        canal_origem=documento.canal_origem,
    )
    return salvar_resultado(resposta)


@app.post("/triagem/arquivo", response_model=RespostaTriagem, tags=["Triagem"])
def triagem_arquivo(
    arquivo: UploadFile = File(..., description="PDF ou imagem do documento clínico"),
    documento_id: Optional[str] = Form(None),
    canal_origem: Optional[str] = Form(None),
):
    """Recebe um PDF ou uma imagem (foto de receita, laudo escaneado) e devolve a triagem."""
    extensao = TIPOS_ACEITOS.get(arquivo.content_type)
    if not extensao:
        raise HTTPException(status_code=415, detail="Formato não suportado. Envie PDF, JPG, PNG ou WEBP.")

    conteudo = arquivo.file.read()
    doc_id = documento_id or _novo_id()
    _guardar_original(doc_id, conteudo, extensao, arquivo.content_type)

    resposta = processar(
        documento_id=doc_id,
        arquivo=conteudo,
        mime_type=arquivo.content_type,
        canal_origem=canal_origem,
    )
    return salvar_resultado(resposta)


@app.get("/auditoria", tags=["Revisão humana"])
def pendentes_de_revisao():
    """Lista os documentos que aguardam revisão humana e ainda não foram revisados."""
    revisados = {_id_do_caminho(c) for c in listar("revisoes/")}
    pendentes = [c for c in listar("auditoria_humana/") if _id_do_caminho(c) not in revisados]
    return {"pendentes": pendentes}


@app.post("/auditoria/{documento_id}/decisao", tags=["Revisão humana"])
def registrar_decisao(documento_id: str, decisao: DecisaoAuditor):
    """Registra se o auditor aprovou ou rejeitou a extração do documento."""
    registro = {
        "documento_id": documento_id,
        "aprovado": decisao.aprovado,
        "auditor": decisao.auditor,
        "observacao": decisao.observacao,
        "data_revisao": datetime.now(timezone.utc).isoformat(),
    }
    caminho = salvar_revisao(documento_id, registro)
    return {"status": "registrado", "caminho_objeto": caminho, **registro}


@app.get("/documentos/{caminho:path}", tags=["Consulta"])
def consultar_documento(caminho: str):
    """Mostra o JSON de um documento salvo no bucket."""
    if not caminho.endswith(".json"):
        raise HTTPException(status_code=400, detail="Informe o caminho de um arquivo .json.")
    return ler_json(caminho)