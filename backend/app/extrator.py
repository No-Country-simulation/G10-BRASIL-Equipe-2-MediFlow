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

# Cadeia de modelos: se um atingir o limite, o próximo é usado.
MODELOS = [
    m.strip()
    for m in os.getenv(
        "GEMINI_MODELOS",
        "gemini-3.8-flash,gemini-flash-latest,gemini-flash-lite-latest",
    ).split(",")
    if m.strip()
]
# Chave principal e chave reserva (opcional), cada uma com cota própria.
CHAVES = [c for c in (os.getenv("GEMINI_API_KEY"), os.getenv("GEMINI_API_KEY_RESERVA")) if c]
TENTATIVAS_POR_MODELO = 3
_clientes = [genai.Client(api_key=chave) for chave in CHAVES]

MENSAGEM_LIMITE = (
    "Limite diário de uso da IA atingido. "
    "O documento foi enviado para revisão humana. Tente novamente mais tarde."
)


class LimiteIAAtingido(Exception):
    """Todas as chaves e modelos atingiram o limite de uso."""


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


def _codigo(erro: Exception) -> Optional[int]:
    return erro.code if isinstance(erro, errors.APIError) else None


def _erro_temporario(erro: Exception) -> bool:
    """Sobrecarga (503) ou limite de uso (429) costumam passar sozinhos."""
    return _codigo(erro) in (429, 500, 503)


def _chamar_gemini(partes: list):
    """Percorre chaves e modelos: limite atingido pula na hora para o próximo."""
    ultimo_erro = None
    limite_atingido = False
    for cliente in _clientes:
        for modelo in MODELOS:
            for tentativa in range(TENTATIVAS_POR_MODELO):
                try:
                    return cliente.models.generate_content(
                        model=modelo,
                        contents=partes,
                        config=types.GenerateContentConfig(
                            response_mime_type="application/json",
                            temperature=0,
                        ),
                    )
                except Exception as erro:
                    ultimo_erro = erro
                    codigo = _codigo(erro)
                    if codigo == 429:
                        limite_atingido = True
                        break  # cota deste modelo acabou: vai para o próximo
                    if codigo == 404:
                        break  # modelo indisponível: vai para o próximo
                    if codigo in (500, 503):
                        time.sleep(2 ** (tentativa + 1))  # espera 2, 4 e 8 segundos
                        continue
                    raise
    if limite_atingido:
        raise LimiteIAAtingido(MENSAGEM_LIMITE)
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