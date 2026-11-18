"""Perfis de prestador de serviço B2B: quais negócios procurar, que sinais indicam necessidade e
qual mensagem de abordagem sugerir. Edite perfis.json (ou aponte PERFIS_ARQUIVO para outro) para
criar o seu."""
import json
import os
import string
from dataclasses import dataclass, field
from pathlib import Path

ARQUIVO = Path(__file__).with_name("perfis.json")

MENSAGEM_PADRAO = ("Olá, equipe {prospect}! Aqui é {meu_nome}, da {minha_empresa}. Atendemos empresas aqui em "
                   "{bairro}. Posso apresentar rapidamente nosso serviço?")


@dataclass
class Perfil:
    chave: str
    nome: str
    alvos: list
    descricao: str = ""
    sinais: list = field(default_factory=list)
    mensagem: str = MENSAGEM_PADRAO


def carregar(caminho=None):
    caminho = Path(caminho or os.environ.get("PERFIS_ARQUIVO") or ARQUIVO)
    dados = json.loads(caminho.read_text(encoding="utf-8"))
    return {k: Perfil(chave=k, nome=v["nome"], alvos=list(v["alvos"]), descricao=v.get("descricao", ""),
                      sinais=[s.lower() for s in v.get("sinais", [])], mensagem=v.get("mensagem") or MENSAGEM_PADRAO)
            for k, v in dados.items()}


def personalizado(alvos, mensagem=None):
    """Perfil montado na hora com os tipos de negócio que o usuário digitou."""
    return Perfil(chave="personalizado", nome="Personalizado", alvos=list(alvos), mensagem=mensagem or MENSAGEM_PADRAO)


def separar_alvos(texto):
    """'padaria, sorveteria; mercado' -> ['padaria', 'sorveteria', 'mercado'] (sem repetidos, até 20)."""
    vistos, saida = set(), []
    for parte in texto.replace(";", ",").replace("\n", ",").split(","):
        p = " ".join(parte.split())[:60]
        if p and p.lower() not in vistos:
            vistos.add(p.lower())
            saida.append(p)
    return saida[:20]


class _Seguro(dict):
    def __missing__(self, chave):
        return ""


def montar_mensagem(modelo, **campos):
    """Preenche {prospect}, {meu_nome}, {minha_empresa}, {bairro}; campos ausentes viram texto vazio
    e chaves desconhecidas no modelo não quebram nada."""
    valores = _Seguro({k: (v or "").strip() for k, v in campos.items()})
    padroes = {"bairro": "sua região", "meu_nome": "[seu nome]", "minha_empresa": "[sua empresa]", "prospect": ""}
    for k, v in padroes.items():
        if not valores.get(k):
            valores[k] = v
    try:
        texto = string.Formatter().vformat(modelo, (), valores)
    except (ValueError, IndexError, KeyError):
        texto = modelo
    return " ".join(texto.split()).replace("equipe !", "equipe!")
