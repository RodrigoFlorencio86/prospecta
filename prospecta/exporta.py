"""Planilha (XLSX ou CSV para Excel brasileiro) e KML (Google My Maps / Google Earth)."""
import csv
import re
from pathlib import Path
from xml.sax.saxutils import escape

from . import busca, rotas, telefone

COLUNAS = ["Prioridade", "Nota", "Nome", "Categoria", "Buscado como", "Distância (km)", "Bairro", "Endereço",
           "Telefone", "Tipo de telefone", "WhatsApp", "WhatsApp (status)", "Abrir WhatsApp com mensagem",
           "E-mails", "Site", "Instagram", "Facebook", "LinkedIn", "Nota Google", "Avaliações",
           "Sinais nas avaliações", "Horário", "Rota da base", "Waze", "Ver no Maps",
           "Status do contato", "Data do contato", "Observações"]
LINKS = {"Abrir WhatsApp com mensagem", "Site", "Instagram", "Facebook", "LinkedIn", "Rota da base", "Waze", "Ver no Maps"}
FORMULA = re.compile(r"^[=+\-@\t\r]")


def linhas(prospects, base, perfil, meu_nome="", minha_empresa="", status=None):
    """Cada prospect como dict com as COLUNAS. status: {chave: (status, data, obs)} do mini-CRM."""
    status = status or {}
    origem = (base.lat, base.lon)
    saida = []
    for p in prospects:
        msg = busca.mensagem_para(p, perfil, meu_nome, minha_empresa)
        st = status.get(p.chave, ("", "", ""))
        saida.append({
            "Prioridade": p.prioridade, "Nota": p.nota, "Nome": p.nome, "Categoria": p.categoria,
            "Buscado como": p.alvo, "Distância (km)": p.distancia_km, "Bairro": p.bairro, "Endereço": p.endereco,
            "Telefone": p.telefone, "Tipo de telefone": p.telefone_tipo,
            "WhatsApp": telefone.Telefone(p.whatsapp, "celular" if len(p.whatsapp) == 11 else "fixo").formatado
            if p.whatsapp else "",
            "WhatsApp (status)": p.whatsapp_status,
            "Abrir WhatsApp com mensagem": telefone.link_whatsapp(p.whatsapp, msg) if p.whatsapp else "",
            "E-mails": p.emails, "Site": p.site if p.site_proprio else "", "Instagram": p.instagram,
            "Facebook": p.facebook, "LinkedIn": p.linkedin, "Nota Google": p.nota_google, "Avaliações": p.avaliacoes,
            "Sinais nas avaliações": ", ".join(p.sinais), "Horário": p.horario,
            "Rota da base": rotas.link_ate(origem, p.lat, p.lon), "Waze": rotas.link_waze(p.lat, p.lon),
            "Ver no Maps": p.link_maps, "Status do contato": st[0], "Data do contato": st[1], "Observações": st[2],
        })
    return saida


def _seguro(v):
    """Texto que o Excel executaria como fórmula ganha um apóstrofo na frente."""
    if isinstance(v, str) and FORMULA.match(v) and not re.fullmatch(r"\+?[\d\s().-]+", v):
        return "'" + v
    return v


def salvar_csv(caminho, dados):
    caminho = Path(caminho)
    with caminho.open("w", encoding="utf-8-sig", newline="") as f:  # BOM + ";" abre certo no Excel pt-BR
        w = csv.DictWriter(f, fieldnames=COLUNAS, delimiter=";")
        w.writeheader()
        for d in dados:
            w.writerow({k: _seguro(v) for k, v in d.items()})
    return caminho


def salvar_xlsx(caminho, dados, resumo=None, rota=None):
    """XLSX com abas Prospects, Rota e Resumo. Sem openpyxl instalado, grava CSV no lugar."""
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill
        from openpyxl.utils import get_column_letter
    except ImportError:
        return salvar_csv(Path(caminho).with_suffix(".csv"), dados)
    wb = Workbook()
    ws = wb.active
    ws.title = "Prospects"
    ws.append(COLUNAS)
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="1F4E79")
    cores = {"A": "C6EFCE", "B": "FFEB9C", "C": "F2F2F2"}
    for i, d in enumerate(dados, start=2):
        ws.append([_seguro(d[k]) for k in COLUNAS])
        ws.cell(i, 1).fill = PatternFill("solid", fgColor=cores.get(d["Prioridade"], "FFFFFF"))
        for j, k in enumerate(COLUNAS, start=1):
            if k in LINKS and d[k]:
                cel = ws.cell(i, j)
                cel.hyperlink = d[k]
                cel.value = {"Abrir WhatsApp com mensagem": "Abrir WhatsApp", "Rota da base": "Rota",
                             "Waze": "Waze", "Ver no Maps": "Maps"}.get(k, d[k])
                cel.font = Font(color="0563C1", underline="single")
    larguras = {"Nome": 34, "Endereço": 45, "Categoria": 22, "Horário": 40, "E-mails": 30, "Observações": 30,
                "Buscado como": 20, "Bairro": 20}
    for j, k in enumerate(COLUNAS, start=1):
        ws.column_dimensions[get_column_letter(j)].width = larguras.get(k, 14)
    ws.freeze_panes = "D2"
    ws.auto_filter.ref = ws.dimensions
    if rota:
        wr = wb.create_sheet("Rota")
        wr.append(["Ordem", "Nome", "Bairro", "Endereço", "Telefone", "Distância da base (km)"])
        for c in wr[1]:
            c.font = Font(bold=True)
        for n, p in enumerate(rota["ordem"], 1):
            wr.append([n, p.nome, p.bairro, p.endereco, p.telefone, p.distancia_km])
        wr.append([])
        wr.append(["Total", f"{rota['km']} km", f"~{rota['minutos']} min com visitas de {rotas.MINUTOS_POR_VISITA} min"])
        for n, link in enumerate(rota["links"], 1):
            wr.append([f"Trecho {n}", "Abrir no Google Maps"])
            c = wr.cell(wr.max_row, 2)
            c.hyperlink, c.font = link, Font(color="0563C1", underline="single")
        for col, w in zip("ABCDEF", (8, 34, 20, 45, 18, 12)):
            wr.column_dimensions[col].width = w
    if resumo:
        wz = wb.create_sheet("Resumo")
        for k, v in resumo.items():
            wz.append([k, v])
        wz.column_dimensions["A"].width = 28
        wz.column_dimensions["B"].width = 70
    caminho = Path(caminho)
    wb.save(caminho)
    return caminho


def salvar_kml(caminho, prospects, base, titulo="Prospects"):
    """Pontos coloridos por prioridade + a base. Importe em mymaps.google.com para ver e planejar."""
    estilos = {"A": "ff00b050", "B": "ff00c0ff", "C": "ff9e9e9e", "base": "ffff0000"}
    partes = ['<?xml version="1.0" encoding="UTF-8"?>', '<kml xmlns="http://www.opengis.net/kml/2.2"><Document>',
              f"<name>{escape(titulo)}</name>"]
    for k, cor in estilos.items():
        partes.append(f'<Style id="{k}"><IconStyle><color>{cor}</color><scale>1.1</scale></IconStyle></Style>')
    partes.append(f'<Placemark><name>Base</name><styleUrl>#base</styleUrl><Point><coordinates>{base.lon:.6f},'
                  f'{base.lat:.6f},0</coordinates></Point></Placemark>')
    for p in prospects:
        desc = "<br/>".join(escape(x) for x in [
            f"Prioridade {p.prioridade} (nota {p.nota})", p.categoria, p.endereco,
            f"Tel: {p.telefone}" if p.telefone else "", f"WhatsApp: {p.whatsapp_status}" if p.whatsapp else "",
            f"{p.distancia_km} km da base"] if x)
        partes.append(f"<Placemark><name>{escape(p.nome)}</name><description><![CDATA[{desc}]]></description>"
                      f"<styleUrl>#{p.prioridade}</styleUrl><Point><coordinates>{p.lon:.6f},{p.lat:.6f},0"
                      f"</coordinates></Point></Placemark>")
    partes.append("</Document></kml>")
    caminho = Path(caminho)
    caminho.write_text("\n".join(partes), encoding="utf-8")
    return caminho


def salvar_resumo_md(caminho, b, perfil, base, prospects, dados, rota=None, top=15):
    """Resumo curto em Markdown de uma busca salva (b), feito para o agente mostrar ao usuário."""
    from . import busca as _busca
    L = b["local"]
    cont = {k: sum(p.prioridade == k for p in prospects) for k in "ABC"}
    modo = _busca.MODOS.get(L.get("modo", "rapido"), {}).get("nome", L.get("modo", ""))
    ocultos = L.get("ocultos") or 0
    ls = [f"# Prospects: {perfil.nome}", "",
          f"- **Local:** {L.get('descricao', '')}", f"- **Raio:** {b['raio_km']:g} km · modo {modo}",
          f"- **Procurado:** {', '.join(perfil.alvos)}",
          f"- **Encontrados:** {len(prospects)} (A: {cont['A']}, B: {cont['B']}, C: {cont['C']})"
          + (f", {ocultos} já recebidos antes ocultados" if ocultos else ""),
          f"- **Com WhatsApp:** {sum(bool(p.whatsapp) for p in prospects)} · **com e-mail:** "
          f"{sum(bool(p.emails) for p in prospects)} · **sem site próprio:** {sum(not p.site_proprio for p in prospects)}"]
    for av in b.get("avisos") or []:
        ls.append(f"- ⚠️ {av}")
    ls += ["", f"## Top {min(top, len(prospects))}", "",
           "| # | Prior. | Nota | Nome | Categoria | Dist. | Bairro | Telefone | WhatsApp |",
           "|---|---|---|---|---|---|---|---|---|"]

    def lim(s):
        return str(s or "").replace("|", "/").replace("\n", " ")

    for i, (p, d) in enumerate(zip(prospects[:top], dados[:top]), 1):
        wa = f"[abrir]({d['Abrir WhatsApp com mensagem']})" if d["Abrir WhatsApp com mensagem"] else "—"
        ls.append(f"| {i} | {p.prioridade} | {p.nota} | {lim(p.nome)} | {lim(p.categoria)} | {p.distancia_km:.1f} km "
                  f"| {lim(p.bairro)} | {lim(p.telefone) or '—'} | {wa} |")
    if rota:
        ls += ["", f"## Rota sugerida ({len(rota['ordem'])} paradas, saindo de {base.descricao})", "",
               " → ".join(p.nome for p in rota["ordem"]), "",
               f"{rota['km']:.1f} km, ~{rota['minutos_carro']} min dirigindo (estimado), ~{rota['minutos']} min com visitas."]
        ls += [f"- [Abrir trecho {i} no Google Maps]({link})" for i, link in enumerate(rota["links"], 1)]
    ls += ["", "## Arquivos", "", "- `relatorio.html`: abra no navegador (botões de WhatsApp, rota, mapa, status)",
           "- `prospects.xlsx`: planilha completa com colunas para acompanhar os contatos",
           "- `prospects.kml`: importe em mymaps.google.com para ver no mapa",
           "- `prospects.json`: os mesmos dados para outros programas"]
    caminho = Path(caminho)
    caminho.write_text("\n".join(ls) + "\n", encoding="utf-8")
    return caminho
