"""
dashboard.py — Alta Viral Scout
Redesigned with Alta brand: white bg, orange accents, black CTAs, rounded corners
"""
import json
import threading
import logging
import subprocess
import sys
import os
import functools
import database as db
import config as cfg_module

from flask import Flask, render_template_string, request, redirect, url_for, jsonify, Response
from werkzeug.utils import secure_filename

logger = logging.getLogger("dashboard")
app    = Flask(__name__)
_scan_callback  = None   # устанавливается из main.py
_login_running  = threading.Event()


# ── HTTP Basic Auth ───────────────────────────────────────────────────────────
def _require_auth(f):
    """
    Защищает маршрут паролем если задана переменная DASHBOARD_PASSWORD.
    Логин — любой (используем 'alta'), пароль — значение переменной.
    Если переменная не задана — доступ открыт (удобно при локальной разработке).
    """
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        password = os.environ.get("DASHBOARD_PASSWORD", "").strip()
        if not password:
            return f(*args, **kwargs)
        auth = request.authorization
        if auth and auth.password == password:
            return f(*args, **kwargs)
        return Response(
            "Alta Viral Scout — требуется авторизация",
            401,
            {"WWW-Authenticate": 'Basic realm="Alta Viral Scout"'},
        )
    return decorated

# ── SVG логотип Alta ──────────────────────────────────────────────────────────
ALTA_LOGO_SVG = """<svg width="72" height="33" viewBox="0 0 314 143" fill="none" xmlns="http://www.w3.org/2000/svg">
<path d="M107.527 87.7005V141.694H80.4344V88.3943C80.4344 78.4736 75.0146 69.8154 66.9732 65.2261C63.0776 62.9997 58.5706 61.7287 53.7651 61.7287C39.0385 61.7287 27.0987 73.6682 27.0987 88.3943C27.0987 103.12 39.0385 115.063 53.7651 115.063C58.5706 115.063 63.0776 113.792 66.9732 111.565V140.526C62.7477 141.595 58.3232 142.161 53.7651 142.161C24.0732 142.161 0 118.088 0 88.3943C0 58.7004 24.0732 34.6309 53.7651 34.6309C58.3232 34.6309 62.7477 35.1967 66.9732 36.2658C71.7474 37.4714 76.2658 39.314 80.4344 41.6996C96.4348 50.8583 107.28 68.0041 107.527 87.7005Z" fill="currentColor"/>
<path d="M313.686 88.3943V141.694H286.588V135.092C278.728 139.59 269.626 142.161 259.921 142.161C247.498 142.161 236.061 137.949 226.959 130.875C223.402 128.111 220.203 124.912 217.442 121.355C210.367 112.253 206.156 100.814 206.156 88.3943C206.156 58.7033 230.227 34.6309 259.921 34.6309C269.626 34.6309 278.728 37.2013 286.588 41.6996C288.789 42.9592 290.893 44.3696 292.883 45.9164L286.588 52.2117L273.408 65.391C269.453 63.0622 264.843 61.7287 259.921 61.7287C245.192 61.7287 233.255 73.6682 233.255 88.3943C233.255 93.3162 234.589 97.9254 236.915 101.883C239.218 105.81 242.502 109.094 246.432 111.4C250.387 113.729 254.999 115.063 259.921 115.063C274.651 115.063 286.588 103.123 286.588 88.3943C286.588 83.4723 285.254 78.8631 282.928 74.9051L286.588 71.2456L302.401 55.4333C309.475 64.5351 313.686 75.9742 313.686 88.3943Z" fill="currentColor"/>
<path d="M208.059 43.9252V51.1731C203.984 57.2125 200.956 63.8462 199.062 70.8467H193.222V141.691H166.299V70.8467H151.465V43.9252H166.299V0H193.222V43.9252H208.059Z" fill="currentColor"/>
<path d="M143.084 0H116.162V141.691H143.084V0Z" fill="currentColor"/>
</svg>"""

# ── Базовый шаблон ────────────────────────────────────────────────────────────
BASE_HTML = """<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Alta Viral Scout</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{
  font-family:-apple-system,BlinkMacSystemFont,"Helvetica Neue",Arial,sans-serif;
  background:#f5f5f5;color:#0d0d0d;font-size:15px;line-height:1.5
}
a{color:inherit;text-decoration:none}

/* ── Nav ── */
.nav{
  background:#fff;
  border-bottom:1px solid #e8e8e8;
  position:sticky;top:0;z-index:100;
  padding:0 40px;
  display:flex;align-items:center;height:60px;gap:0
}
.nav-logo{display:flex;align-items:center;color:#0d0d0d;margin-right:40px;flex-shrink:0}
.nav-links{display:flex;align-items:center;gap:4px;flex:1}
.nav-link{
  font-size:14px;color:#6e6e73;padding:6px 14px;border-radius:8px;
  transition:all .15s;font-weight:450
}
.nav-link:hover{color:#0d0d0d;background:#f5f5f5}
.nav-link.active{color:#0d0d0d;font-weight:550}
.nav-actions{display:flex;align-items:center;gap:10px}

/* ── Page ── */
.page{max-width:1200px;margin:0 auto;padding:40px 32px}
h1{font-size:26px;font-weight:650;letter-spacing:-.4px;margin-bottom:4px}
.subtitle{color:#6e6e73;font-size:14px;margin-bottom:32px}
h2{font-size:17px;font-weight:600;letter-spacing:-.2px;margin-bottom:16px}

/* ── Stat cards ── */
.cards{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-bottom:32px}
.card{
  background:#fff;border-radius:18px;padding:22px 24px;
  border:1px solid #e8e8e8;
}
.card-label{
  font-size:11px;font-weight:550;color:#6e6e73;
  text-transform:uppercase;letter-spacing:.07em;margin-bottom:10px
}
.card-value{font-size:34px;font-weight:700;letter-spacing:-.5px;line-height:1}
.card-value.green {color:#1a7a3c}
.card-value.orange{color:#e85d00}
.card-value.purple{color:#5e35b1}
.card-value.black {color:#0d0d0d}

/* ── Section ── */
.section{
  background:#fff;border-radius:18px;border:1px solid #e8e8e8;
  padding:24px;margin-bottom:20px
}
.section-header{
  display:flex;align-items:center;justify-content:space-between;margin-bottom:20px
}

/* ── Table wrapper (scrollable!) ── */
.table-wrap{overflow-x:auto;-webkit-overflow-scrolling:touch;margin:0 -4px}
table{width:100%;border-collapse:collapse;font-size:14px;min-width:900px}
thead th{
  text-align:left;padding:9px 14px;
  border-bottom:2px solid #f0f0f0;
  font-size:11px;font-weight:600;color:#6e6e73;
  text-transform:uppercase;letter-spacing:.06em;white-space:nowrap
}
tbody td{
  padding:12px 14px;border-bottom:1px solid #f5f5f5;
  vertical-align:top
}
tbody tr:last-child td{border-bottom:none}
tbody tr:hover{background:#fafafa}

/* ── Badges ── */
.badge{
  display:inline-flex;align-items:center;gap:4px;
  padding:3px 10px;border-radius:20px;
  font-size:12px;font-weight:550;white-space:nowrap
}
.badge-brand{background:#f0eeff;color:#5833c2}
.badge-site {background:#e6f0ff;color:#0050cc}
.badge-ai   {background:#e6fff2;color:#0d6e3a}
.badge-viral{background:#fff2e6;color:#c44f00}

/* ── Score colors ── */
.score-ultra{color:#0d6e3a;font-weight:700}
.score-high {color:#c44f00;font-weight:700}
.score-low  {color:#6e6e73;font-weight:500}

/* ── Buttons ── */
.btn{
  display:inline-flex;align-items:center;gap:7px;
  padding:10px 20px;border-radius:12px;
  font-size:14px;font-weight:550;cursor:pointer;
  border:none;transition:all .15s;line-height:1;white-space:nowrap
}
.btn-black{background:#0d0d0d;color:#fff}
.btn-black:hover{background:#2a2a2a;color:#fff}
.btn-orange{background:#ff6d39;color:#fff}
.btn-orange:hover{background:#e85d2a;color:#fff}
.btn-ghost{
  background:transparent;color:#0d0d0d;
  border:1.5px solid #d0d0d0
}
.btn-ghost:hover{background:#f5f5f5;border-color:#b0b0b0}
.btn-sm{padding:7px 14px;font-size:13px;border-radius:9px}
.btn-danger{background:#fff;color:#cc0011;border:1.5px solid #cc0011}
.btn-danger:hover{background:#fff5f5}

/* ── TikTok login button ── */
.btn-tiktok{
  background:#0d0d0d;color:#fff;
  display:inline-flex;align-items:center;gap:8px
}
.btn-tiktok:hover{background:#2a2a2a;color:#fff}
.tiktok-icon{width:16px;height:16px;flex-shrink:0}

/* ── Tags ── */
.tag-list{display:flex;flex-wrap:wrap;gap:8px;margin-top:8px}
.tag{
  display:inline-flex;align-items:center;gap:6px;
  background:#f5f5f5;border:1px solid #e0e0e0;
  border-radius:9px;padding:5px 11px;font-size:13px
}
.tag-rm{cursor:pointer;color:#aaa;font-size:16px;line-height:1;font-weight:400}
.tag-rm:hover{color:#cc0011}

/* ── Inputs ── */
input[type=text],input[type=number],input[type=password]{
  border:1.5px solid #e0e0e0;border-radius:12px;padding:10px 14px;
  font-size:14px;width:100%;outline:none;transition:all .15s;background:#fff
}
input:focus{border-color:#0d0d0d;box-shadow:0 0 0 3px rgba(13,13,13,.08)}

.form-row{margin-bottom:20px}
label{font-size:13px;color:#6e6e73;display:block;margin-bottom:6px;font-weight:500}

/* ── History rows ── */
.scan-row{
  display:flex;align-items:center;gap:12px;
  padding:14px 0;border-bottom:1px solid #f0f0f0
}
.scan-row:last-child{border-bottom:none}
.scan-status-done{color:#1a7a3c;font-size:12px;font-weight:600}
.scan-status-err {color:#cc0011;font-size:12px;font-weight:600}
.scan-status-run {color:#ff6d39;font-size:12px;font-weight:600}

/* ── Flash ── */
.flash{
  padding:13px 16px;border-radius:12px;margin-bottom:20px;
  font-size:14px;font-weight:500
}
.flash-ok {background:#e6fff2;color:#0d6e3a;border:1px solid #b5dfc5}
.flash-err{background:#fff5f5;color:#cc0011;border:1px solid #f5c2c7}
.flash-info{background:#fff9f0;color:#a04200;border:1px solid #f5d9b8}

.empty{text-align:center;padding:56px 24px;color:#aaa;font-size:14px}

/* ── Filter chips ── */
.filter-chips{display:flex;gap:8px;flex-wrap:wrap}
.chip{
  padding:5px 14px;border-radius:20px;font-size:13px;font-weight:500;
  cursor:pointer;border:1.5px solid #e0e0e0;background:#fff;
  color:#6e6e73;transition:all .15s
}
.chip:hover{border-color:#0d0d0d;color:#0d0d0d}
.chip.active{background:#0d0d0d;color:#fff;border-color:#0d0d0d}

/* ── Login modal ── */
.modal-bg{
  display:none;position:fixed;inset:0;
  background:rgba(0,0,0,.45);z-index:200;
  align-items:center;justify-content:center;backdrop-filter:blur(4px)
}
.modal-bg.open{display:flex}
.modal{
  background:#fff;border-radius:22px;padding:36px 40px;
  max-width:460px;width:90%;text-align:center;
  box-shadow:0 24px 64px rgba(0,0,0,.18)
}
.modal h3{font-size:20px;font-weight:650;letter-spacing:-.3px;margin-bottom:10px}
.modal p{color:#6e6e73;font-size:14px;line-height:1.6;margin-bottom:24px}
.modal-actions{display:flex;gap:10px;justify-content:center}

@media(max-width:768px){
  .cards{grid-template-columns:repeat(2,1fr)}
  .nav{padding:0 20px}
  .page{padding:24px 16px}
}
</style>
</head>
<body>
<nav class="nav">
  <a href="/" class="nav-logo">""" + ALTA_LOGO_SVG + """</a>
  <div class="nav-links">
    <a href="/" class="nav-link {{ 'active' if page=='home' else '' }}">Дашборд</a>
    <a href="/history" class="nav-link {{ 'active' if page=='history' else '' }}">История</a>
    <a href="/settings" class="nav-link {{ 'active' if page=='settings' else '' }}">Настройки</a>
  </div>
  <div class="nav-actions">
    <a href="#" class="btn btn-tiktok btn-sm" onclick="openLoginModal();return false">
      <svg class="tiktok-icon" viewBox="0 0 24 24" fill="currentColor">
        <path d="M19.59 6.69a4.83 4.83 0 01-3.77-4.25V2h-3.45v13.67a2.89 2.89 0 01-2.88 2.5 2.89 2.89 0 01-2.89-2.89 2.89 2.89 0 012.89-2.89c.28 0 .54.04.79.1V9.01a6.33 6.33 0 00-.79-.05 6.34 6.34 0 00-6.34 6.34 6.34 6.34 0 006.34 6.34 6.34 6.34 0 006.33-6.34V8.77a8.22 8.22 0 004.81 1.54V6.86a4.85 4.85 0 01-1.04-.17z"/>
      </svg>
      TikTok аккаунт
    </a>
  </div>
</nav>

<!-- Login Modal -->
<div class="modal-bg" id="loginModal">
  <div class="modal">
    <div style="font-size:36px;margin-bottom:12px">
      <svg width="40" height="40" viewBox="0 0 24 24" fill="#0d0d0d">
        <path d="M19.59 6.69a4.83 4.83 0 01-3.77-4.25V2h-3.45v13.67a2.89 2.89 0 01-2.88 2.5 2.89 2.89 0 01-2.89-2.89 2.89 2.89 0 012.89-2.89c.28 0 .54.04.79.1V9.01a6.33 6.33 0 00-.79-.05 6.34 6.34 0 00-6.34 6.34 6.34 6.34 0 006.34 6.34 6.34 6.34 0 006.33-6.34V8.77a8.22 8.22 0 004.81 1.54V6.86a4.85 4.85 0 01-1.04-.17z"/>
      </svg>
    </div>
    <h3>Войти в TikTok</h3>
    <p>Откроется браузер для авторизации.<br>Войди в аккаунт вручную — сессия сохранится автоматически.</p>
    <div class="modal-actions">
      <button class="btn btn-ghost" onclick="closeLoginModal()">Отмена</button>
      <form method="post" action="/login-tiktok" style="display:inline">
        <button class="btn btn-black" type="submit">Открыть браузер</button>
      </form>
    </div>
  </div>
</div>

{% block body %}{% endblock %}

<script>
function openLoginModal(){document.getElementById('loginModal').classList.add('open')}
function closeLoginModal(){document.getElementById('loginModal').classList.remove('open')}
document.getElementById('loginModal').addEventListener('click',function(e){
  if(e.target===this)closeLoginModal()
})
</script>
</body>
</html>"""

# ── Общий макрос таблицы видео ────────────────────────────────────────────────
_VIDEO_TABLE = """
{% macro video_table(videos) %}
{% if videos %}
<div class="table-wrap">
<table>
  <thead>
    <tr>
      <th style="width:40px">#</th>
      <th style="width:90px">Score</th>
      <th style="width:130px">Категория</th>
      <th style="width:110px">Просмотры</th>
      <th style="width:110px">Подписчики</th>
      <th style="width:120px">Источник</th>
      <th style="min-width:200px">Хук</th>
      <th style="min-width:240px">Адаптация для Alta</th>
      <th style="width:90px">Ссылка</th>
    </tr>
  </thead>
  <tbody>
  {% for v in videos %}
  <tr>
    <td style="color:#aaa;font-size:13px">{{ loop.index }}</td>
    <td>
      {% if v.score >= 500 %}<span class="score-ultra">{{ "%.0f"|format(v.score) }}x</span>
      {% elif v.score >= 100 %}<span class="score-high">{{ "%.0f"|format(v.score) }}x</span>
      {% else %}<span class="score-low">{{ "%.0f"|format(v.score) }}x</span>{% endif %}
    </td>
    <td>
      {% set cat_v = v.category or 'вирал' %}
      {% if cat_v == 'брендинг' %}<span class="badge badge-brand">🎨 брендинг</span>
      {% elif cat_v == 'сайты' %}<span class="badge badge-site">🌐 сайты</span>
      {% elif cat_v == 'ии-контент' %}<span class="badge badge-ai">🤖 ии-контент</span>
      {% else %}<span class="badge badge-viral">⚡ вирал</span>{% endif %}
    </td>
    <td style="font-weight:500">{{ "{:,}".format(v.views).replace(",", " ") }}</td>
    <td style="color:#6e6e73">{{ "{:,}".format(v.followers).replace(",", " ") }}</td>
    <td style="font-size:12px;color:#6e6e73;white-space:nowrap">
      {{ v.source | replace('search:','') | replace('account:','@') | replace('fyp','FYP') }}
    </td>
    <td style="font-size:13px;color:#3a3a3a;line-height:1.4">{{ v.gemini_hook or '—' }}</td>
    <td style="font-size:13px;color:#0d0d0d;line-height:1.4">{{ v.gemini_adaptation or '—' }}</td>
    <td>
      <a href="{{ v.url }}" target="_blank" class="btn btn-ghost btn-sm"
         style="padding:5px 12px;font-size:12px">▶ смотреть</a>
    </td>
  </tr>
  {% endfor %}
  </tbody>
</table>
</div>
{% else %}
<div class="empty">
  <div style="font-size:32px;margin-bottom:12px">📭</div>
  Нет данных — запусти первое сканирование
</div>
{% endif %}
{% endmacro %}
"""

# ── Главная страница — вся библиотека видео ───────────────────────────────────
HOME_HTML = BASE_HTML.replace("{% block body %}{% endblock %}", _VIDEO_TABLE + """
<div class="page">
  <div style="display:flex;align-items:flex-start;justify-content:space-between;margin-bottom:32px">
    <div>
      <h1>Библиотека</h1>
      <p class="subtitle">Все уникальные видео за всё время · {{ stats.total or 0 }} роликов · {{ stats.authors or 0 }} авторов</p>
    </div>
    <form method="post" action="/run">
      <button class="btn btn-orange" type="submit">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>
        Запустить скан
      </button>
    </form>
  </div>

  {% if msg %}
  <div class="flash flash-{{ 'ok' if msg_type=='ok' else ('info' if msg_type=='info' else 'err') }}">{{ msg }}</div>
  {% endif %}

  <div class="cards">
    <div class="card">
      <div class="card-label">Всего видео</div>
      <div class="card-value black">{{ stats.total or '—' }}</div>
    </div>
    <div class="card">
      <div class="card-label">Авторов</div>
      <div class="card-value green">{{ stats.authors or '—' }}</div>
    </div>
    <div class="card">
      <div class="card-label">Сверхвирал 500x+</div>
      <div class="card-value orange">{{ stats.ultra or 0 }}</div>
    </div>
    <div class="card">
      <div class="card-label">Макс. Score</div>
      <div class="card-value purple">{{ "%.0f"|format(stats.max_score) if stats.max_score else '—' }}x</div>
    </div>
  </div>

  <div class="section">
    <div class="section-header">
      <h2 style="margin:0">Все ролики</h2>
      <div class="filter-chips">
        <a href="?cat=all"        class="chip {{ 'active' if cat=='all' else '' }}">Все</a>
        <a href="?cat=брендинг"   class="chip {{ 'active' if cat=='брендинг' else '' }}">🎨 Брендинг</a>
        <a href="?cat=сайты"      class="chip {{ 'active' if cat=='сайты' else '' }}">🌐 Сайты</a>
        <a href="?cat=ии-контент" class="chip {{ 'active' if cat=='ии-контент' else '' }}">🤖 ИИ-контент</a>
        <a href="?cat=вирал"      class="chip {{ 'active' if cat=='вирал' else '' }}">⚡ Вирал</a>
      </div>
    </div>
    {{ video_table(videos) }}
  </div>
</div>
""")

# ── История сканирований ──────────────────────────────────────────────────────
HISTORY_HTML = BASE_HTML.replace("{% block body %}{% endblock %}", """
<div class="page">
  <h1>История сканирований</h1>
  <p class="subtitle">Все запуски — нажми чтобы открыть выборку</p>

  <div class="section">
    {% if scans %}
    {% for s in scans %}
    <div class="scan-row">
      <div style="flex:1">
        <span style="font-weight:600">#{{ s.id }}</span>
        <span style="color:#6e6e73;font-size:13px;margin-left:12px">{{ s.started_at[:16] }}</span>
      </div>
      <div style="color:#6e6e73;font-size:13px;width:180px">
        {{ s.total_scraped or 0 }} просканировано · <b style="color:#0d0d0d">{{ s.total_relevant or 0 }}</b> прошли
      </div>
      <div style="width:120px">
        {% if s.status == 'done' %}
          <span class="scan-status-done">✓ Готово</span>
        {% elif 'error' in s.status %}
          <span class="scan-status-err">✗ Ошибка</span>
        {% else %}
          <span class="scan-status-run">⟳ В процессе</span>
        {% endif %}
      </div>
      <a href="/scan/{{ s.id }}" class="btn btn-ghost btn-sm">Открыть →</a>
    </div>
    {% endfor %}
    {% else %}
    <div class="empty">
      <div style="font-size:32px;margin-bottom:12px">📋</div>
      История пуста
    </div>
    {% endif %}
  </div>
</div>
""")

# ── Страница конкретного скана ────────────────────────────────────────────────
SCAN_HTML = BASE_HTML.replace("{% block body %}{% endblock %}", _VIDEO_TABLE + """
<div class="page">
  <div style="display:flex;align-items:center;gap:16px;margin-bottom:32px">
    <a href="/history" class="btn btn-ghost btn-sm">← История</a>
    <div>
      <h1>Скан #{{ scan.id }}</h1>
      <p class="subtitle">{{ scan.started_at[:16] }} · {{ scan.total_scraped or 0 }} просканировано · {{ scan.total_relevant or 0 }} прошли фильтр</p>
    </div>
  </div>

  <div class="cards">
    <div class="card">
      <div class="card-label">Видео в скане</div>
      <div class="card-value black">{{ stats.total or '—' }}</div>
    </div>
    <div class="card">
      <div class="card-label">Релевантных (7+)</div>
      <div class="card-value green">{{ stats.relevant or 0 }}</div>
    </div>
    <div class="card">
      <div class="card-label">Сверхвирал 500x+</div>
      <div class="card-value orange">{{ stats.ultra or 0 }}</div>
    </div>
    <div class="card">
      <div class="card-label">Макс. Score</div>
      <div class="card-value purple">{{ "%.0f"|format(stats.max_score) if stats.max_score else '—' }}x</div>
    </div>
  </div>

  <div class="section">
    <div class="section-header">
      <h2 style="margin:0">Видео из этого скана</h2>
      <div class="filter-chips">
        <a href="?cat=all"        class="chip {{ 'active' if cat=='all' else '' }}">Все</a>
        <a href="?cat=брендинг"   class="chip {{ 'active' if cat=='брендинг' else '' }}">🎨 Брендинг</a>
        <a href="?cat=сайты"      class="chip {{ 'active' if cat=='сайты' else '' }}">🌐 Сайты</a>
        <a href="?cat=ии-контент" class="chip {{ 'active' if cat=='ии-контент' else '' }}">🤖 ИИ-контент</a>
        <a href="?cat=вирал"      class="chip {{ 'active' if cat=='вирал' else '' }}">⚡ Вирал</a>
      </div>
    </div>
    {{ video_table(videos) }}
  </div>
</div>
""")

# ── Настройки ─────────────────────────────────────────────────────────────────
SETTINGS_HTML = BASE_HTML.replace("{% block body %}{% endblock %}", """
<div class="page">
  <h1>Настройки</h1>
  <p class="subtitle">Управление источниками и интеграциями</p>

  {% if msg %}
  <div class="flash flash-{{ 'ok' if msg_type=='ok' else 'err' }}">{{ msg }}</div>
  {% endif %}

  <form method="post" action="/settings/save">
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:20px">

    <div class="section">
      <h2>Telegram</h2>
      <div class="form-row">
        <label>Bot Token</label>
        <input type="password" name="telegram_bot_token" value="{{ cfg.telegram_bot_token }}" placeholder="1234567890:AAA...">
      </div>
      <div class="form-row">
        <label>Chat ID (группа команды)</label>
        <input type="text" name="telegram_chat_id" value="{{ cfg.telegram_chat_id }}" placeholder="-100123456789">
      </div>
      <div class="form-row">
        <label>Время дайджеста (час, 0–23)</label>
        <input type="number" name="schedule_hour" value="{{ cfg.schedule_hour }}" min="0" max="23">
      </div>
      <div class="form-row">
        <label>URL дашборда <span style="color:#6e6e73;font-size:11px">— вставь публичный адрес (Railway / ngrok) для ссылок в Telegram</span></label>
        <input type="text" name="dashboard_url" value="{{ cfg.get('dashboard_url','') }}" placeholder="https://tiktok-production-xxxx.up.railway.app">
      </div>
    </div>

    <div class="section">
      <h2>Gemini AI</h2>
      <div class="form-row">
        <label>API Key</label>
        <input type="password" name="gemini_api_key" value="{{ cfg.gemini_api_key }}" placeholder="AIza...">
      </div>
      <div class="form-row">
        <label>Анализировать топ-N видео</label>
        <input type="number" name="gemini_top_n" value="{{ cfg.gemini_top_n }}" min="10" max="100">
      </div>
      <div class="form-row">
        <label>Минимальный Score</label>
        <input type="number" name="min_score" value="{{ cfg.min_score }}" min="5">
      </div>
      <div class="form-row">
        <label>Минимальные просмотры в дайджест <span style="color:#6e6e73;font-size:11px">— видео с меньшим числом не попадут в Telegram</span></label>
        <input type="number" name="min_views" value="{{ cfg.get('min_views', 50000) }}" min="0" step="1000">
      </div>
      <div class="form-row" style="margin-top:16px;padding-top:16px;border-top:1px solid #f0f0f0">
        <label>CapSolver API Key <span style="color:#1a7a3c;font-size:11px">— $0.50 бесплатно</span></label>
        <input type="password" name="capsolver_api_key" value="{{ cfg.get('capsolver_api_key','') }}" placeholder="CAP-xxxxxxxxxxxxxxxx">
      </div>
      <div class="form-row" style="margin-top:16px;padding-top:16px;border-top:1px solid #f0f0f0">
        <label>Bright Data CDP URL <span style="color:#1a7a3c;font-size:11px">— удалённый браузер с авто-решением капч</span></label>
        <input type="password" name="brightdata_cdp_url" value="{{ cfg.get('brightdata_cdp_url','') }}" placeholder="wss://brd-customer-...@brd.superproxy.io:9222">
      </div>
      <div class="form-row" style="margin-top:16px;padding-top:16px;border-top:1px solid #f0f0f0">
        <label>Прокси <span style="color:#6e6e73;font-size:11px">— используется только если Bright Data не задан</span></label>
        <input type="text" name="proxy" value="{{ cfg.get('proxy','') }}" placeholder="socks5://user:pass@host:port">
      </div>
    </div>

  </div>

  <div class="section">
    <h2>TikTok сессия</h2>
    <p style="font-size:13px;color:#6e6e73;margin-bottom:16px">
      Для работы на сервере (Railway) нужно загрузить файл сессии с Mac.<br>
      На Mac запусти бота, залогинься — файл <code>tiktok_session.json</code> появится в папке проекта.
    </p>
    <form method="post" action="/upload-session" enctype="multipart/form-data"
          style="display:flex;gap:12px;align-items:center">
      <input type="file" name="session_file" accept=".json"
             style="flex:1;border:1.5px dashed #d0d0d0;padding:10px;border-radius:12px;
                    background:#fafafa;font-size:13px;cursor:pointer">
      <button type="submit" class="btn btn-black" style="flex-shrink:0">Загрузить сессию</button>
    </form>
    {% if session_ok %}
    <p style="margin-top:12px;font-size:13px;color:#1a7a3c">✓ Сессия активна</p>
    {% else %}
    <p style="margin-top:12px;font-size:13px;color:#c44f00">⚠ Сессия не найдена</p>
    {% endif %}
  </div>

  <div style="display:grid;grid-template-columns:1fr 1fr;gap:20px;margin-top:0">

    <div class="section">
      <h2>Хэштеги</h2>
      <div class="tag-list" id="tags-list">
        {% for tag in cfg.hashtags %}
        <span class="tag">#{{ tag }}<span class="tag-rm" onclick="removeTag(this,'hashtag','{{ tag }}')">×</span></span>
        {% endfor %}
      </div>
      <input type="hidden" name="hashtags" id="hashtags-input" value="{{ cfg.hashtags | join(',') }}">
      <div style="display:flex;gap:8px;margin-top:14px">
        <input type="text" id="new-tag" placeholder="Добавить хэштег" style="flex:1">
        <button type="button" class="btn btn-ghost btn-sm" onclick="addTag('hashtag')" style="flex-shrink:0">+ Добавить</button>
      </div>
    </div>

    <div class="section">
      <h2>Seed-аккаунты</h2>
      <div class="tag-list" id="accounts-list">
        {% for acc in cfg.seed_accounts %}
        <span class="tag">@{{ acc }}<span class="tag-rm" onclick="removeTag(this,'account','{{ acc }}')">×</span></span>
        {% endfor %}
      </div>
      <input type="hidden" name="seed_accounts" id="accounts-input" value="{{ cfg.seed_accounts | join(',') }}">
      <div style="display:flex;gap:8px;margin-top:14px">
        <input type="text" id="new-account" placeholder="Добавить аккаунт" style="flex:1">
        <button type="button" class="btn btn-ghost btn-sm" onclick="addTag('account')" style="flex-shrink:0">+ Добавить</button>
      </div>
    </div>

  </div>

  <div class="section">
    <h2>Поисковые запросы</h2>
    <div class="tag-list" id="queries-list">
      {% for q in cfg.search_queries %}
      <span class="tag">{{ q }}<span class="tag-rm" onclick="removeTag(this,'query','{{ q }}')">×</span></span>
      {% endfor %}
    </div>
    <input type="hidden" name="search_queries" id="queries-input" value="{{ cfg.search_queries | join('||') }}">
    <div style="display:flex;gap:8px;margin-top:14px">
      <input type="text" id="new-query" placeholder="Например: logo reveal" style="flex:1;max-width:400px">
      <button type="button" class="btn btn-ghost btn-sm" onclick="addTag('query')" style="flex-shrink:0">+ Добавить</button>
    </div>
  </div>

  <div style="display:flex;gap:12px;justify-content:flex-end;margin-top:8px">
    <button type="submit" class="btn btn-black">Сохранить настройки</button>
  </div>
  </form>
</div>

<script>
const store = {
  hashtag: {{ cfg.hashtags | tojson }},
  account: {{ cfg.seed_accounts | tojson }},
  query:   {{ cfg.search_queries | tojson }},
};
const inputs = {hashtag:'hashtags-input', account:'accounts-input', query:'queries-input'};
const lists  = {hashtag:'tags-list', account:'accounts-list', query:'queries-list'};
const sep    = {hashtag:',', account:',', query:'||'};

function syncInput(type) {
  document.getElementById(inputs[type]).value = store[type].join(sep[type]);
}
function addTag(type) {
  const id = type==='hashtag'?'new-tag':type==='account'?'new-account':'new-query';
  const inp = document.getElementById(id);
  const val = inp.value.trim().replace(/^[@#]/, '');
  if (!val || store[type].includes(val)) { inp.value=''; return; }
  store[type].push(val);
  const prefix = type==='hashtag'?'#':type==='account'?'@':'';
  const el = document.createElement('span');
  el.className='tag';
  el.innerHTML=prefix+val+'<span class="tag-rm" onclick="removeTag(this,\''+type+'\',\''+val+'\')">×</span>';
  document.getElementById(lists[type]).appendChild(el);
  syncInput(type);
  inp.value='';
}
function removeTag(el, type, val) {
  store[type]=store[type].filter(x=>x!==val);
  el.parentElement.remove();
  syncInput(type);
}
// Enter key in tag inputs
['new-tag','new-account','new-query'].forEach(function(id){
  const el=document.getElementById(id);
  if(!el)return;
  const type=id==='new-tag'?'hashtag':id==='new-account'?'account':'query';
  el.addEventListener('keypress',function(e){if(e.key==='Enter'){e.preventDefault();addTag(type);}});
});
</script>
""")


# ── Flask маршруты ────────────────────────────────────────────────────────────

@app.route("/")
@_require_auth
def home():
    """Библиотека — все уникальные видео за всё время."""
    try:
        msg      = request.args.get("msg", "")
        msg_type = request.args.get("msg_type", "ok")
        cat      = request.args.get("cat", "all")

        stats  = db.get_all_videos_stats()
        videos = db.get_all_videos(limit=500, cat=cat if cat != "all" else None)

        return render_template_string(HOME_HTML,
            page="home", stats=stats or {}, videos=videos or [],
            msg=msg, msg_type=msg_type, cat=cat)
    except Exception as e:
        logger.exception(f"Ошибка главной страницы: {e}")
        return "<h2>Временная ошибка</h2><p>Обнови страницу через минуту.</p>", 500


@app.route("/history")
@_require_auth
def history():
    scans = db.get_recent_scans(50)
    return render_template_string(HISTORY_HTML, page="history", scans=scans)


@app.route("/scan/<int:scan_id>")
@_require_auth
def scan_detail(scan_id):
    """Детальный отчёт по конкретному скану."""
    try:
        cat    = request.args.get("cat", "all")
        scan   = db.get_scan_by_id(scan_id)
        if not scan:
            return redirect(url_for("history"))
        stats  = db.get_stats(scan_id)
        videos = db.get_scan_videos(scan_id, limit=300)
        if cat and cat != "all":
            videos = [v for v in videos if v.get("category") == cat]
        return render_template_string(SCAN_HTML,
            page="history", scan=scan, stats=stats or {},
            videos=videos or [], cat=cat)
    except Exception as e:
        logger.exception(f"Ошибка страницы скана: {e}")
        return "<h2>Ошибка</h2>", 500


@app.route("/settings")
@_require_auth
def settings():
    msg      = request.args.get("msg", "")
    msg_type = request.args.get("msg_type", "ok")
    cfg      = cfg_module.load()
    session_ok = os.path.exists(cfg.get("session_file", "tiktok_session.json"))
    return render_template_string(SETTINGS_HTML,
        page="settings", cfg=cfg, msg=msg, msg_type=msg_type,
        session_ok=session_ok)


@app.route("/settings/save", methods=["POST"])
@_require_auth
def settings_save():
    try:
        c = cfg_module.load()
        c["telegram_bot_token"] = request.form.get("telegram_bot_token", "")
        c["telegram_chat_id"]   = request.form.get("telegram_chat_id", "")
        c["gemini_api_key"]     = request.form.get("gemini_api_key", "")
        c["schedule_hour"]      = int(request.form.get("schedule_hour", 9))
        c["gemini_top_n"]       = int(request.form.get("gemini_top_n", 50))
        c["min_score"]          = int(request.form.get("min_score", 10))
        c["min_views"]          = int(request.form.get("min_views", 50000))
        c["capsolver_api_key"]   = request.form.get("capsolver_api_key", "")
        c["brightdata_cdp_url"]  = request.form.get("brightdata_cdp_url", "").strip()
        dashboard_url = request.form.get("dashboard_url", "").strip()
        if dashboard_url:
            c["dashboard_url"] = dashboard_url
        c["proxy"]              = request.form.get("proxy", "").strip()
        c["hashtags"]      = [x.strip() for x in request.form.get("hashtags","").split(",") if x.strip()]
        c["seed_accounts"] = [x.strip() for x in request.form.get("seed_accounts","").split(",") if x.strip()]
        c["search_queries"]= [x.strip() for x in request.form.get("search_queries","").split("||") if x.strip()]
        cfg_module.save(c)
        logger.info(f"Настройки сохранены в {cfg_module.CONFIG_FILE}")
        return redirect(url_for("settings", msg=f"Сохранено ✓ ({cfg_module.CONFIG_FILE})", msg_type="ok"))
    except Exception as e:
        logger.exception(f"Ошибка сохранения настроек: {e}")
        return redirect(url_for("settings", msg=f"Ошибка сохранения: {e}", msg_type="err"))


@app.route("/run", methods=["POST"])
@_require_auth
def run_now():
    if _scan_callback:
        t = threading.Thread(target=_scan_callback, daemon=True)
        t.start()
        return redirect(url_for("home", msg="Сканирование запущено ▶", msg_type="ok"))
    return redirect(url_for("home", msg="Колбек не установлен", msg_type="err"))


@app.route("/upload-session", methods=["POST"])
@_require_auth
def upload_session():
    """Загружает tiktok_session.json на сервер."""
    f = request.files.get("session_file")
    if not f or not f.filename:
        return redirect(url_for("settings", msg="Файл не выбран", msg_type="err"))
    try:
        import base64
        cfg  = cfg_module.load()
        path = cfg.get("session_file", "tiktok_session.json")
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        data = f.read()
        # Сохраняем файл
        with open(path, "wb") as fout:
            fout.write(data)
        # Дублируем в БД — выживает при рестартах
        db.kv_set("tiktok_session_b64", base64.b64encode(data).decode())
        logger.info(f"Сессия загружена и сохранена в БД: {path}")
        return redirect(url_for("settings",
            msg="✓ Сессия успешно загружена — следующий скан пройдёт авторизованно",
            msg_type="ok"))
    except Exception as e:
        logger.exception(f"Ошибка загрузки сессии: {e}")
        return redirect(url_for("settings", msg="Ошибка при загрузке файла", msg_type="err"))


@app.route("/login-tiktok", methods=["POST"])
@_require_auth
def login_tiktok():
    """Запускает браузер для ручной авторизации TikTok."""
    if _login_running.is_set():
        return redirect(url_for("home",
            msg="Авторизация уже запущена — проверь браузер", msg_type="info"))

    def _do_login():
        _login_running.set()
        try:
            script = os.path.join(os.path.dirname(__file__), "login.py")
            subprocess.run([sys.executable, script], timeout=180)
            logger.info("TikTok логин завершён")
        except subprocess.TimeoutExpired:
            logger.warning("Логин TikTok: таймаут 3 мин")
        except Exception as e:
            logger.error(f"Ошибка логина: {e}")
        finally:
            _login_running.clear()

    t = threading.Thread(target=_do_login, daemon=True, name="tiktok-login")
    t.start()
    return redirect(url_for("home",
        msg="Браузер открывается... Войди в TikTok и закрой окно — сессия сохранится автоматически.",
        msg_type="info"))


@app.route("/api/status")
def api_status():
    scan = db.get_latest_scan()
    return jsonify(scan or {})


@app.route("/api/ingest", methods=["POST"])
def api_ingest():
    """
    Принимает данные скана от локальной копии и сохраняет в Railway БД.
    Используется для синхронизации: локалка → Railway.
    Защищён токеном из config.json → sync_token.
    """
    cfg = cfg_module.load()
    expected = cfg.get("sync_token", "").strip()
    if expected:
        auth = request.headers.get("Authorization", "")
        if auth != f"Bearer {expected}":
            return jsonify({"error": "Unauthorized"}), 401

    try:
        payload    = request.get_json(force=True)
        scan_data  = payload.get("scan", {})
        videos     = payload.get("videos", [])

        if not videos:
            return jsonify({"ok": True, "scan_id": None, "videos": 0,
                            "msg": "Нет видео — ничего не сохранено"})

        # Создаём скан с оригинальными timestamps от локалки
        from datetime import datetime as _dt
        scan_id = db.create_scan_from_remote(
            started_at    = scan_data.get("started_at",  _dt.now().isoformat()),
            finished_at   = scan_data.get("finished_at", _dt.now().isoformat()),
            total_scraped = scan_data.get("total_scraped",  0),
            total_relevant= scan_data.get("total_relevant", len(videos)),
        )

        # Сохраняем видео (INSERT OR IGNORE — не дублируем по URL)
        db.save_videos(scan_id, videos)

        # Обновляем Gemini-поля по URL
        for v in videos:
            if v.get("gemini_hook") or v.get("gemini_adaptation"):
                db.update_gemini(
                    url        = v["url"],
                    relevance  = v.get("gemini_relevance", 0),
                    hook       = v.get("gemini_hook", ""),
                    adaptation = v.get("gemini_adaptation", ""),
                    category   = v.get("category", "вирал"),
                    why_viral  = v.get("gemini_why_viral", ""),
                    priority   = v.get("gemini_priority", "средний"),
                )

        logger.info(f"[ingest] Синхронизировано: скан #{scan_id}, {len(videos)} видео")
        return jsonify({"ok": True, "scan_id": scan_id, "videos": len(videos)})

    except Exception as e:
        logger.exception(f"[ingest] Ошибка: {e}")
        return jsonify({"error": str(e)}), 500


def start(scan_cb=None, host="127.0.0.1", port=5001):
    global _scan_callback
    _scan_callback = scan_cb
    app.run(host=host, port=port, debug=False, use_reloader=False)
