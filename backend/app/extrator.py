"""Leitura do documento com o Gemini: classifica e extrai os dados clínicos."""
import os
import time
from typing import Optional

from dotenv import load_dotenv
from google import genai
from google.genai import errors, types
from pydantic import BaseModel, Field

from app.schemas import (
    Classificacao,
    DadosExtraidos,
    NivelPrioridade,
    ResultadoExame,
    TipoDocumento,
)

load_dotenv()

MODELO = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
MODELO_RESERVA = os.getenv("GEMINI_MODEL_RESERVA", "gemini-flash-latest")
TENTATIVAS_POR_MODELO = 3
_cliente = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))


class ResultadoExtracao(BaseModel):
    classificacao: Classificacao
    dados_extraidos: DadosExtraidos
    score_confianca_extracao: float = Field(ge=0, le=1)


def _valores(lista) -> str:
    return ", ".join(f'"{item.value}"' for item in lista)


INSTRUCOES = f"""
Você é o agente de triagem do MediFlow. Leia o documento clínico e responda
SOMENTE com um JSON válido, sem texto antes ou depois, neste formato:

{{
  "classificacao": {{
    "tipo_documento": um destes valores: {_valores(TipoDocumento)},
    "especialidade": texto ou null,
    "nivel_prioridade": um destes valores: {_valores(NivelPrioridade)},
    "score_confianca_classificacao": número de 0 a 1
  }},
  "dados_extraidos": {{
    "paciente": {{"nome": texto ou null, "idade": número inteiro ou null, "identificador": texto ou null}},
    "medico_solicitante": {{"nome": texto ou null, "crm": texto ou null}},
    "exame_realizado": texto ou null,
    "exames_solicitados": lista de textos,
    "resultado_exame": um destes valores: {_valores(ResultadoExame)},
    "diagnostico_principal": texto ou null,
    "cid_sugerido": código CID-10 ou null,
    "medicamentos": lista de {{"nome": texto, "dosagem": texto ou null, "posologia": texto ou null, "controlado": true ou false}},
    "campos_ilegiveis_ou_ausentes": lista com o nome dos campos importantes ilegíveis ou faltando
  }},
  "score_confianca_extracao": número de 0 a 1
}}

Regras:
- Nunca invente dados. Se algo não estiver no documento, use null e cite o campo em "campos_ilegiveis_ou_ausentes".
- "Urgente": achado crítico, risco imediato ou pedido explícito de urgência.
- "Atenção": resultado alterado sem risco imediato, ou medicamento controlado ou de alto risco.
- "Rotina": demais casos.
- "resultado_exame" só vale para laudos; nos outros documentos use "Não se aplica".
- Marque "controlado": true para medicamentos de controle especial (Portaria 344, tarja preta).
- Reduza os scores de confiança se o texto estiver confuso, incompleto ou ilegível.
"""


def _erro_temporario(erro: Exception) -> bool:
    """Sobrecarga (503) ou limite de uso (429) costumam passar sozinhos."""
    return isinstance(erro, errors.APIError) and erro.code in (429, 500, 503)


def _chamar_gemini(partes: list):
    """Tenta o modelo principal e, se continuar falhando, o modelo reserva."""
    ultimo_erro = None
    for modelo in (MODELO, MODELO_RESERVA):
        for tentativa in range(TENTATIVAS_POR_MODELO):
            try:
                return _cliente.models.generate_content(
                    model=modelo,
                    contents=partes,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        temperature=0,
                    ),
                )
            except Exception as erro:
                ultimo_erro = erro
                if not _erro_temporario(erro):
                    raise
                time.sleep(2 ** (tentativa + 1))  # espera 2, 4 e 8 segundos
    raise ultimo_erro


def extrair(
    texto: Optional[str] = None,
    arquivo: Optional[bytes] = None,
    mime_type: Optional[str] = None,
) -> ResultadoExtracao:
    """Envia o documento ao Gemini e devolve os dados já validados pelo Pydantic."""
    partes = [INSTRUCOES]
    if arquivo:
        partes.append(types.Part.from_bytes(data=arquivo, mime_type=mime_type))
    if texto:
        partes.append(f"Documento:\n{texto}")
    if len(partes) == 1:
        raise ValueError("Nenhum conteúdo de documento foi enviado.")

    resposta = _chamar_gemini(partes)
    return ResultadoExtracao.model_validate_json(resposta.text)