"""Relatório em HTML para abrir no navegador: lista filtrável, botões de WhatsApp / rota / Waze,
mapa e status de contato salvo no próprio navegador."""
import json
from html import escape
from pathlib import Path

from . import busca, rotas, telefone

MODELO = """<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light dark">
<title>Prospects — __TITULO__</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"
      integrity="sha384-sHL9NAb7lN7rfvG5lfHpm643Xkcjzp4jFvuavGOndn6pjVqS6ny56CAt3nsEVT4H" crossorigin="anonymous" referrerpolicy="no-referrer">
<style>
:root { --fundo:#f6f7f9; --cartao:#fff; --texto:#1c2430; --suave:#5d6b7c; --linha:#e3e7ec; --a:#1e8e3e; --b:#e3a008; --c:#9aa5b1; --azul:#1f5fbf;
  color-scheme:light dark; accent-color:var(--azul); }
@media (prefers-color-scheme: dark) { :root { --fundo:#12161c; --cartao:#1b2129; --texto:#e8edf2; --suave:#9aa7b5; --linha:#2b333d; } }
* { box-sizing:border-box; }
:focus-visible { outline:2px solid var(--azul); outline-offset:2px; }
body { margin:0; font:15px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif; background:var(--fundo); color:var(--texto); }
header { padding:20px 16px 8px; max-width:1100px; margin:auto; }
h1 { font-size:1.35rem; margin:0 0 4px; }
.sub { color:var(--suave); }
.kpis { display:flex; flex-wrap:wrap; gap:8px; margin:14px 0 4px; }
.kpi { background:var(--cartao); border:1px solid var(--linha); border-radius:10px; padding:8px 12px; }
.kpi b { font-size:1.15rem; display:block; }
main { max-width:1100px; margin:auto; padding:0 16px 40px; }
.aviso-mapa { background:var(--cartao); border:1px solid var(--linha); border-radius:10px; padding:10px 12px; margin:10px 0 0; font-size:.9rem; color:var(--suave); }
#mapa { height:340px; border-radius:12px; border:1px solid var(--linha); margin:10px 0 14px; }
.filtros { display:flex; flex-wrap:wrap; gap:8px; margin:6px 0 12px; }
.filtros input, .filtros select { padding:8px 10px; border-radius:8px; border:1px solid var(--linha); background:var(--cartao); color:var(--texto); font:inherit; }
.filtros input { flex:1; min-width:180px; }
.lista { display:grid; gap:10px; }
.p { background:var(--cartao); border:1px solid var(--linha); border-left:5px solid var(--c); border-radius:10px; padding:12px 14px; }
.p:nth-child(n+4) { content-visibility:auto; contain-intrinsic-size:auto 160px; }
.p.A { border-left-color:var(--a); } .p.B { border-left-color:var(--b); }
.topo { display:flex; justify-content:space-between; gap:10px; align-items:baseline; }
.nome { font-weight:650; font-size:1.02rem; }
.nota { font-weight:700; white-space:nowrap; }
.info { color:var(--suave); font-size:.92rem; margin-top:2px; overflow-wrap:anywhere; }
.acoes { display:flex; flex-wrap:wrap; gap:6px; margin-top:10px; align-items:center; }
.acoes a { text-decoration:none; padding:6px 10px; border-radius:8px; border:1px solid var(--linha); color:var(--texto); font-size:.9rem; }
.acoes a.wa { background:#1fa855; border-color:#1fa855; color:#fff; }
.acoes select { padding:5px 8px; border-radius:8px; border:1px solid var(--linha); background:var(--cartao); color:var(--texto); font:inherit; font-size:.9rem; }
.rota { background:var(--cartao); border:1px solid var(--linha); border-radius:10px; padding:12px 14px; margin-bottom:14px; }
.rota a { color:var(--azul); }
.vazio { color:var(--suave); padding:20px 0; }
footer { color:var(--suave); font-size:.85rem; max-width:1100px; margin:auto; padding:0 16px 30px; }
</style></head><body>
<header>
  <h1>Prospects: __TITULO__</h1>
  <div class="sub">__SUB__</div>
  <div class="kpis" id="kpis"></div>
</header>
<main>
  <div id="mapa-aviso" class="aviso-mapa" style="display:none">🗺️ Os pontos abaixo estão sem o mapa de ruas
    porque este arquivo foi aberto direto do computador. Para ver as ruas, abra a busca no painel
    (<code>python -m prospecta painel</code>, ou peça ao Claude "abra o painel") ou importe o arquivo
    <code>prospects.kml</code> em <a href="https://www.google.com/maps/d/" target="_blank" rel="noopener">Google My Maps</a>.</div>
  <div id="mapa"></div>
  <div class="rota" id="rota"></div>
  <div class="filtros">
    <input id="q" type="search" placeholder="Filtrar por nome, bairro ou categoria" aria-label="Filtrar por nome, bairro ou categoria">
    <select id="fp" aria-label="Prioridade"><option value="">Todas as prioridades</option><option>A</option><option>B</option><option>C</option></select>
    <select id="fw" aria-label="WhatsApp"><option value="">Com ou sem WhatsApp</option><option value="1">Só com WhatsApp</option></select>
    <select id="fs" aria-label="Status do contato"><option value="">Qualquer status</option><option value="-">Sem status</option></select>
  </div>
  <div class="lista" id="lista"></div>
</main>
<footer>Dados públicos do Google Maps e dos sites das empresas. Use para contato comercial B2B,
identifique-se e respeite quem pedir para não ser contatado (LGPD). O status de cada contato fica
salvo só neste navegador; para guardar de vez, use a planilha.</footer>
<script id="dados" type="application/json">__DADOS__</script>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"
        integrity="sha384-cxOPjt7s7Iz04uaHJceBmS+qpjv2JkIHNVcuOrM+YHwZOmJGBXI00mdUXEq65HTH" crossorigin="anonymous" referrerpolicy="no-referrer"></script>
<script>
const D = JSON.parse(document.getElementById('dados').textContent);
const STATUS = ["", "⭐ Interessado", "📨 Contatado", "📍 Visitar", "🤝 Cliente", "🚫 Sem interesse"];
const CHAVE = 'prospecta:' + D.id;
let st = {};
try { st = JSON.parse(localStorage.getItem(CHAVE) || '{}'); } catch (e) {}
const salvar = () => { try { localStorage.setItem(CHAVE, JSON.stringify(st)); } catch (e) {} };
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fs = document.getElementById('fs');
STATUS.slice(1).forEach(s => fs.add(new Option(s, s)));
const k = D.kpis;
document.getElementById('kpis').innerHTML = Object.entries(k).map(([n, v]) => `<div class="kpi"><b>${esc(v)}</b>${esc(n)}</div>`).join('');
const r = D.rota;
document.getElementById('rota').innerHTML = r ? `<b>🗺️ Rota sugerida</b> com os ${r.ordem.length} melhores: ${r.ordem.map(esc).join(' → ')}<br>
  ${esc(r.km)} km · ~${esc(r.minutos_carro)} min dirigindo (estimado) · ` +
  r.links.map((l, i) => `<a href="${esc(l)}" target="_blank" rel="noopener">abrir ${r.links.length > 1 ? 'trecho ' + (i + 1) : 'no Google Maps'}</a>`).join(' · ') : '';
const cor = {A:'#1e8e3e', B:'#e3a008', C:'#9aa5b1'};
let mapa = null;
if (window.L) {
  mapa = L.map('mapa').setView([D.base.lat, D.base.lon], 14);
  if (location.protocol === 'file:') {
    // Aberto direto do arquivo, o navegador não tem origem para informar e o OpenStreetMap recusa as imagens do
    // mapa (403). Mostramos só os pontos, sobre fundo neutro, e explicamos como ver o mapa de ruas.
    document.getElementById('mapa-aviso').style.display = 'block';
  } else {
    L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {maxZoom:19, attribution:'&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
      referrerPolicy:'strict-origin-when-cross-origin'}).addTo(mapa);
  }
  L.circle([D.base.lat, D.base.lon], {radius:D.raio_m, color:'#1f5fbf', weight:1, fillOpacity:.04}).addTo(mapa);
  L.circleMarker([D.base.lat, D.base.lon], {radius:8, color:'#1f5fbf', fillOpacity:1}).addTo(mapa).bindPopup('Base');
  D.itens.forEach((p, i) => L.circleMarker([p.lat, p.lon], {radius:6, color:cor[p.prioridade], fillOpacity:.85})
    .addTo(mapa).bindPopup(`<b>${i + 1}. ${esc(p.nome)}</b><br>${esc(p.categoria)}<br>${esc(p.telefone)}`));
} else { document.getElementById('mapa').style.display = 'none'; }
function desenhar() {
  const q = document.getElementById('q').value.toLowerCase(), fp = document.getElementById('fp').value,
        fw = document.getElementById('fw').value, fsv = fs.value;
  const itens = D.itens.map((p, i) => [p, i]).filter(([p]) =>
    (!q || (p.nome + ' ' + p.bairro + ' ' + p.categoria + ' ' + p.endereco).toLowerCase().includes(q)) &&
    (!fp || p.prioridade === fp) && (!fw || p.wa_link) &&
    (!fsv || (fsv === '-' ? !st[p.chave] : st[p.chave] === fsv)));
  document.getElementById('lista').innerHTML = itens.length ? itens.map(([p, i]) => `
    <div class="p ${esc(p.prioridade)}">
      <div class="topo"><span class="nome">${i + 1}. ${esc(p.nome)}</span><span class="nota">${esc(p.prioridade)} · ${esc(p.nota)}</span></div>
      <div class="info">${esc(p.categoria)} · ${esc(p.distancia)} · ${esc(p.bairro || p.endereco)}</div>
      <div class="info">${[p.telefone && '📞 ' + esc(p.telefone) + (p.wa_status ? ' (WhatsApp ' + esc(p.wa_status) + ')' : ''),
        p.emails && '✉️ ' + esc(p.emails), p.avaliacoes && '⭐ ' + esc(p.nota_google) + ' (' + esc(p.avaliacoes) + ')',
        p.sinais && '🔥 ' + esc(p.sinais)].filter(Boolean).join(' · ')}</div>
      <div class="acoes">
        ${p.wa_link ? `<a class="wa" href="${esc(p.wa_link)}" target="_blank" rel="noopener">💬 WhatsApp</a>` : ''}
        <a href="${esc(p.rota)}" target="_blank" rel="noopener">🗺️ Rota</a>
        <a href="${esc(p.waze)}" target="_blank" rel="noopener">🚗 Waze</a>
        ${p.maps ? `<a href="${esc(p.maps)}" target="_blank" rel="noopener">📍 Maps</a>` : ''}
        ${p.site ? `<a href="${esc(p.site)}" target="_blank" rel="noopener">🌐 Site</a>` : ''}
        ${p.instagram ? `<a href="${esc(p.instagram)}" target="_blank" rel="noopener">📸 Instagram</a>` : ''}
        <select data-k="${esc(p.chave)}" aria-label="Status de ${esc(p.nome)}">${STATUS.map(s => `<option ${st[p.chave] === s ? 'selected' : ''} value="${esc(s)}">${s || 'Status…'}</option>`).join('')}</select>
      </div>
    </div>`).join('') : '<div class="vazio">Nenhum prospect com esses filtros.</div>';
}
document.getElementById('lista').addEventListener('change', ev => {
  if (ev.target.dataset.k) { st[ev.target.dataset.k] = ev.target.value; if (!ev.target.value) delete st[ev.target.dataset.k]; salvar(); }
});
['q', 'fp', 'fw', 'fs'].forEach(id => document.getElementById(id).addEventListener('input', desenhar));
desenhar();
</script></body></html>
"""


def _seguro_url(u):
    return u if isinstance(u, str) and u.startswith(("https://", "http://")) else ""


def gerar(caminho, prospects, base, perfil, raio_m, meu_nome="", minha_empresa="", rota=None, titulo=""):
    origem = (base.lat, base.lon)
    itens = []
    for p in prospects:
        msg = busca.mensagem_para(p, perfil, meu_nome, minha_empresa)
        itens.append({
            "chave": p.chave, "nome": p.nome, "categoria": p.categoria, "bairro": p.bairro, "endereco": p.endereco,
            "lat": p.lat, "lon": p.lon, "distancia": f"{p.distancia_km:.1f} km".replace(".", ","),
            "telefone": p.telefone, "wa_status": p.whatsapp_status,
            "wa_link": telefone.link_whatsapp(p.whatsapp, msg) if p.whatsapp else "",
            "emails": p.emails, "nota_google": p.nota_google, "avaliacoes": p.avaliacoes,
            "sinais": ", ".join(p.sinais), "nota": p.nota, "prioridade": p.prioridade,
            "rota": rotas.link_ate(origem, p.lat, p.lon), "waze": rotas.link_waze(p.lat, p.lon),
            "maps": _seguro_url(p.link_maps), "site": _seguro_url(p.site) if p.site_proprio else "",
            "instagram": _seguro_url(p.instagram),
        })
    kpis = {"prospects": len(prospects),
            "prioridade A": sum(p.prioridade == "A" for p in prospects),
            "com WhatsApp": sum(bool(p.whatsapp) for p in prospects),
            "com e-mail": sum(bool(p.emails) for p in prospects),
            "raio": f"{raio_m / 1000:g} km".replace(".", ",")}
    dados = {"id": Path(caminho).parent.name or "prospecta", "base": {"lat": base.lat, "lon": base.lon},
             "raio_m": raio_m, "itens": itens, "kpis": kpis,
             "rota": {"ordem": [p.nome for p in rota["ordem"]], "km": f"{rota['km']:.1f}".replace(".", ","),
                      "minutos_carro": rota["minutos_carro"], "links": rota["links"]} if rota else None}
    bruto = json.dumps(dados, ensure_ascii=False).replace("</", "<\\/")  # nada fecha o <script> antes da hora
    titulo = titulo or perfil.nome
    html = (MODELO.replace("__TITULO__", escape(titulo))
            .replace("__SUB__", escape(f"{perfil.nome} · até {raio_m / 1000:g} km de {base.descricao}"))
            .replace("__DADOS__", bruto))
    caminho = Path(caminho)
    caminho.write_text(html, encoding="utf-8")
    return caminho
