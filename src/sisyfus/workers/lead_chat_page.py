"""Standalone conversational operator page; the backend owns all mission truth."""

PAGE = r'''<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="color-scheme" content="light">
<title>Sisyfus · 一起把想法做成</title>
<style nonce="NONCE">
:root{--paper:#faf9f5;--side:#f0eee7;--ink:#302d29;--muted:#71695f;--line:#ded9cf;--accent:#995638;--accent-hover:#7c432b;--wash:#f4e9df;--good:#486452;--bad:#a34335;--font:"PingFang SC","Microsoft YaHei","Noto Sans CJK SC",sans-serif}
*{box-sizing:border-box}html,body{margin:0;height:100%;background:var(--paper);color:var(--ink);font:14px/1.65 var(--font)}body{overflow:hidden}button,input,textarea,select{font:inherit;color:inherit}button,a,input,textarea,summary{-webkit-tap-highlight-color:transparent}button{cursor:pointer}button:disabled{cursor:default;opacity:.48}button,a{touch-action:manipulation}button{border:0;background:none}a{color:var(--accent);text-decoration:none}a:hover{text-decoration:underline}button:focus-visible,a:focus-visible,summary:focus-visible{outline:2px solid var(--accent);outline-offset:4px}input:focus,textarea:focus{outline:none}input:focus-visible{border-color:var(--accent);box-shadow:0 0 0 2px var(--wash)}[hidden]{display:none!important}.sr-only{position:absolute;width:1px;height:1px;overflow:hidden;clip-path:inset(50%);white-space:nowrap}.muted{color:var(--muted)}.eyebrow{font-size:11px;letter-spacing:.1em;color:var(--muted)}.primary{background:var(--accent);color:#fffaf6;border-radius:9px;padding:10px 17px;font-weight:500}.primary:hover:not(:disabled){background:var(--accent-hover)}.secondary{border:1px solid var(--line);border-radius:8px;padding:8px 13px;background:var(--paper)}.secondary:hover:not(:disabled){background:var(--side)}.text-button{color:var(--accent);padding:5px 0}.icon-button{width:38px;height:38px;border-radius:8px;font-size:20px;flex-shrink:0}.icon-button:hover{background:var(--side)}.flex{display:flex;align-items:center;gap:10px}.min-zero{min-width:0}.wrap{flex-wrap:wrap}.stack>*+*{margin-top:12px}.small{font-size:12px}.error{color:var(--bad)}.good{color:var(--good)}.plain-list{padding-left:20px;margin:8px 0}.plain-list li+li{margin-top:7px}.prose{white-space:pre-wrap;overflow-wrap:anywhere;word-break:break-word}.app{display:flex;height:100vh;height:100dvh;width:100%;isolation:isolate}.sidebar{width:244px;flex-shrink:0;background:var(--side);display:flex;flex-direction:column;padding:25px 16px 16px;border-right:1px solid var(--line)}.brand{padding:0 10px 22px;display:flex;align-items:center;gap:10px}.brand-mark{font:32px/1 Georgia,serif;color:var(--accent)}.brand-name{font:23px/1.2 Georgia,"Songti SC",serif;letter-spacing:-.5px}.brand-caption{font-size:11px;color:var(--muted);margin-top:3px}.sidebar-close{display:none;margin-left:auto}.new-chat{display:flex;align-items:center;gap:10px;width:100%;border:1px solid #c8b6a5;border-radius:9px;padding:10px 12px;text-align:left;background:#f7f4ee}.new-chat:hover:not(:disabled){background:var(--wash)}.new-chat span:first-child{font-size:20px;color:var(--accent)}.nav-scroll{overflow:auto;flex:1;padding-top:22px;min-height:0;scrollbar-width:thin}.nav-heading{margin:0 10px 8px;color:var(--muted);font-size:11px;font-weight:500;letter-spacing:.08em}.nav-heading.missions-heading{margin-top:28px}.nav-item{display:block;width:100%;text-align:left;border-radius:7px;padding:9px 10px;margin:2px 0;min-height:47px}.nav-item:hover{background:#e8e3d9}.nav-item[aria-current="true"]{background:#e5ded2}.nav-title{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:13px}.nav-meta{display:block;color:var(--muted);font-size:11px;margin-top:2px}.nav-empty{padding:6px 10px;color:var(--muted);font-size:12px}.sidebar-footer{border-top:1px solid var(--line);padding:14px 9px 0;margin-top:16px;display:flex;justify-content:space-between;gap:10px;font-size:12px}.workspace{min-width:0;flex:1;display:flex;flex-direction:column}.topbar{height:69px;flex-shrink:0;display:flex;align-items:center;justify-content:space-between;gap:14px;padding:0 30px;border-bottom:1px solid transparent}.topbar-title{font-size:13px;min-width:0;overflow:hidden;white-space:nowrap;text-overflow:ellipsis}.topbar-subtitle{font-size:11px;color:var(--muted);display:block}.topbar-actions{display:flex;align-items:center;gap:17px;flex-shrink:0}.connection{color:var(--muted);font-size:11px;display:flex;align-items:center;gap:6px}.connection::before{content:"";width:5px;height:5px;border-radius:50%;background:var(--good);flex-shrink:0}.connection.offline::before{background:var(--bad)}.mobile-menu{display:none}.settings-trigger{font-size:12px;padding:8px 0;color:var(--muted)}.settings-trigger:hover{color:var(--accent)}.scroll-area{flex:1;min-height:0;overflow:auto;scroll-behavior:smooth;scrollbar-width:thin;overscroll-behavior:contain}.content{width:min(100%,780px);margin:0 auto;padding:24px 38px 35px}.welcome{padding:clamp(30px,10vh,115px) 0 30px}.welcome-symbol{font:42px/1.2 Georgia,serif;color:var(--accent);margin-bottom:21px}.welcome h1{font:400 clamp(27px,3.2vw,38px)/1.55 "Songti SC","STSong",Georgia,serif;letter-spacing:-.025em;margin:0 0 14px}.welcome-intro{margin:0;color:var(--muted);max-width:470px;font-size:14px}.suggestions{margin-top:31px;display:flex;flex-direction:column;align-items:flex-start;gap:3px}.suggestion{text-align:left;color:#63584c;padding:9px 0;font-size:13px;display:flex;align-items:center;gap:12px}.suggestion::before{content:"↗";color:var(--accent)}.suggestion:hover{color:var(--accent)}.welcome-footnote{font-size:11px;color:var(--muted);margin-top:24px}.message{margin-bottom:28px}.message.user{display:flex;flex-direction:column;align-items:flex-end}.message-author{font-size:11px;color:var(--muted);margin-bottom:7px;display:flex;align-items:center;gap:7px}.message.assistant .message-author::before{content:"✳";color:var(--accent);font-size:16px}.message-text{font-size:15px;line-height:1.9;width:100%}.message.user .message-text{width:auto;max-width:88%;padding:11px 17px;border-radius:15px 15px 4px 15px;background:#eee9df}.notice{border-top:1px solid var(--line);padding:15px 0;margin:18px 0;color:var(--muted);font-size:13px}.notice p{margin:0 0 8px}.notice .text-button{margin-right:14px}.notice.error{color:var(--bad)}.waiting{font-size:13px;color:var(--muted);padding:14px 0;display:flex;align-items:center;gap:10px}.waiting-dots{display:flex;gap:4px}.waiting-dots i{width:4px;height:4px;border-radius:50%;background:var(--accent);animation:breathe 1.4s ease-in-out infinite}.waiting-dots i:nth-child(2){animation-delay:.18s}.waiting-dots i:nth-child(3){animation-delay:.36s}@keyframes breathe{0%,80%,100%{opacity:.25}40%{opacity:1}}.proposal{margin:28px 0 12px;border:1px solid #d7ccbe;border-radius:12px;padding:23px;background:#f6f3ed}.proposal h2{font:400 23px/1.5 "Songti SC",Georgia,serif;margin:5px 0 17px}.proposal h3,.mission-section h3{font-size:13px;font-weight:600;margin:20px 0 8px}.draft-label{font-size:11px;color:var(--accent);letter-spacing:.06em}.proposal p{margin:8px 0}.proposal-preview{color:var(--muted);font-size:13px;line-height:1.8}.proposal-preview-tasks{list-style:none;counter-reset:preview;margin:15px 0;padding:0}.proposal-preview-tasks li{counter-increment:preview;display:flex;gap:12px;align-items:baseline;padding:5px 0;font-size:13px;min-width:0}.proposal-preview-tasks li::before{content:counter(preview,decimal-leading-zero);color:var(--accent);font-size:10px;flex-shrink:0}.proposal-preview-tasks span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;min-width:0}.full-proposal{border-top:1px solid var(--line);margin-top:16px;padding-top:13px;font-size:13px}.full-proposal>summary{cursor:pointer;color:var(--accent);font-size:12px}.full-proposal h3{font-size:12px}.full-proposal-body{padding-top:12px}.proposal h2{font-size:20px;margin-bottom:12px}.proposal-tasks{list-style:none;counter-reset:tasks;margin:12px 0 0;padding:0}.proposal-tasks>li{counter-increment:tasks;position:relative;padding:13px 0 13px 30px;border-top:1px solid var(--line)}.proposal-tasks>li::before{content:counter(tasks,decimal-leading-zero);position:absolute;left:0;top:16px;font-size:11px;color:var(--accent)}.task-title{font-size:14px;font-weight:500}.task-acceptance{font-size:12px;color:var(--muted);margin-top:5px}.proposal-actions{padding:8px 0 18px}.confirmation{padding:20px 0;margin:12px 0;border-top:1px solid #cbb7a4;border-bottom:1px solid var(--line)}.confirmation h3{font-size:15px;margin:0 0 10px}.context-line{display:grid;grid-template-columns:60px minmax(0,1fr);gap:8px;font-size:12px;margin:8px 0}.context-line dt{color:var(--muted)}.context-line dd{margin:0;overflow-wrap:anywhere}.permission{display:flex;align-items:flex-start;gap:9px;font-size:13px;margin:16px 0;cursor:pointer}.permission input{margin:5px 0 0;accent-color:var(--accent);flex-shrink:0}.permission small{display:block;color:var(--muted);font-size:11px;margin-top:4px}.composer-wrap{flex-shrink:0;padding:12px 38px max(17px,env(safe-area-inset-bottom));width:min(100%,780px);margin:0 auto}.composer{border:1px solid #d5cdbf;border-radius:15px;background:#fdfcf8;padding:13px 15px 10px;box-shadow:0 3px 14px #47362206}.composer:focus-within{border-color:#af8264;box-shadow:0 0 0 2px #9956380a}.composer textarea{width:100%;resize:none;border:0;background:none;display:block;line-height:1.7;font-size:14px;min-height:48px;max-height:180px;padding:2px 0;overflow-y:auto;field-sizing:content}.composer textarea::placeholder{color:#8b8174}.composer-footer{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-top:9px}.composer-context{color:var(--muted);font-size:11px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;text-align:left;padding:4px 0;min-width:0}.send{height:34px;width:34px;border-radius:9px;background:var(--accent);color:#fffaf6;font-size:22px;line-height:1;flex-shrink:0}.send:hover:not(:disabled){background:var(--accent-hover)}.composer-hint{display:flex;justify-content:space-between;gap:12px;color:var(--muted);font-size:10px;padding:9px 3px 0;flex-wrap:wrap}.mission-kicker{color:var(--accent);font-size:11px}.mission-title{font:400 27px/1.5 "Songti SC",Georgia,serif;margin:8px 0 22px;overflow-wrap:anywhere}.mission-report{border-left:2px solid #c69d80;padding:0 0 0 17px;margin:18px 0 25px}.mission-report h2{font-size:16px;font-weight:500;margin:0 0 7px}.mission-report p{margin:5px 0;color:var(--muted);font-size:13px}.mission-section{margin:28px 0}.task-row{padding:13px 0;border-bottom:1px solid var(--line)}.task-row summary{list-style:none;cursor:pointer;display:flex;justify-content:space-between;align-items:flex-start;gap:16px}.task-row summary::-webkit-details-marker{display:none}.task-row summary::after{content:"+";color:var(--muted)}.task-row[open] summary::after{content:"−"}.task-label{flex:1;min-width:0;overflow-wrap:anywhere}.task-meta{display:block;color:var(--muted);font-size:11px;margin-top:4px}.task-detail{font-size:12px;padding:12px 0 4px;color:var(--muted)}.thread-entry{padding:12px 0 12px 18px;border-left:1px solid var(--line);position:relative;margin-left:3px}.thread-entry::before{content:"";position:absolute;left:-3px;top:19px;width:5px;height:5px;border-radius:50%;background:#bc977d}.thread-entry h4{font-size:13px;font-weight:500;margin:0 0 5px}.thread-entry p{font-size:12px;color:var(--muted);margin:3px 0}.mission-toolbar{display:flex;gap:9px;flex-wrap:wrap;margin:22px 0 14px}.danger-button{color:var(--bad)}.stop-note{margin:10px 0 18px;font-size:12px;color:var(--muted)}.drawer{position:fixed;right:0;top:0;bottom:0;width:370px;max-width:100%;background:var(--paper);border-left:1px solid var(--line);z-index:30;display:flex;flex-direction:column;box-shadow:-12px 0 40px #302d2910}.drawer-header{display:flex;align-items:center;justify-content:space-between;padding:21px 24px;border-bottom:1px solid var(--line)}.drawer-header h2{font-size:16px;font-weight:500;margin:0}.drawer-body{padding:23px 24px;overflow:auto;min-height:0}.drawer-intro{font-size:12px;color:var(--muted);margin:0 0 24px}.field{display:block;margin:20px 0;font-size:13px}.field input,.field select{display:block;margin:8px 0;width:100%;background:#fdfcf8;border:1px solid var(--line);border-radius:7px;padding:10px 11px;font-size:12px}.field small{display:block;color:var(--muted);font-size:11px}.form-actions{display:flex;gap:13px;align-items:center;margin-top:22px}.settings-section{border-top:1px solid var(--line);padding:17px 0;margin-top:23px}.settings-section summary{cursor:pointer;font-size:13px}.settings-section h3{font-size:12px;font-weight:500;margin:0 0 9px}.check-row{padding:10px 0;border-bottom:1px solid var(--line);font-size:12px;overflow-wrap:anywhere}.check-row strong{font-weight:500}.check-row p{font-size:11px;margin:5px 0;color:var(--muted)}.debug-block{border-bottom:1px solid var(--line);padding:14px 0}.debug-block summary{cursor:pointer;font-size:12px}.debug-block pre{font:11px/1.7 ui-monospace,Menlo,monospace;white-space:pre-wrap;overflow-wrap:anywhere;max-height:400px;overflow:auto;color:var(--muted)}.backdrop{position:fixed;inset:0;background:#30282033;z-index:20;border:0;width:100%;height:100%;cursor:default}.global-note{padding:9px 30px;background:var(--wash);font-size:12px;overflow-wrap:anywhere}.global-note p{margin:0}.jump-latest{position:absolute;right:24px;bottom:155px;border:1px solid var(--line);background:var(--paper);padding:7px 12px;border-radius:20px;font-size:11px;color:var(--muted)}.workspace{position:relative}
@media(min-width:1500px){.sidebar{width:266px}.content,.composer-wrap{width:820px}}
@media(max-width:850px){.sidebar{width:210px;padding-left:11px;padding-right:11px}.topbar{padding:0 22px}.content{padding:18px 28px 30px}.composer-wrap{padding-left:28px;padding-right:28px}.connection{max-width:110px}.connection span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
@media(max-width:700px){.sidebar{display:none;position:fixed;left:0;top:0;bottom:0;width:min(290px,86vw);z-index:30;padding:23px 16px;background:var(--side)}.sidebar.open{display:flex}.sidebar-close{display:block}.mobile-menu{display:block}.topbar{height:63px;padding:0 14px;gap:8px}.topbar-actions{gap:11px}.topbar-title{font-size:12px}.topbar-subtitle{font-size:10px}.connection{font-size:10px;max-width:72px}.settings-trigger{font-size:11px}.content{padding:14px 22px 24px}.welcome{padding-top:clamp(25px,7vh,65px)}.welcome h1{font-size:29px}.welcome-intro{font-size:13px}.welcome-symbol{margin-bottom:16px;font-size:35px}.suggestions{margin-top:22px}.suggestion{font-size:12px;line-height:1.6}.composer-wrap{padding:9px 16px max(12px,env(safe-area-inset-bottom))}.composer{padding:11px 13px 9px}.composer-hint{font-size:9px}.message-text{font-size:14px}.proposal{padding:18px}.drawer{width:min(370px,100vw)}.drawer-header{padding:18px 22px}.drawer-body{padding:20px 22px}.global-note{padding:9px 18px}.mission-title{font-size:24px}.jump-latest{right:18px;bottom:145px}}
@media(prefers-reduced-motion:reduce){*,*::before,*::after{animation:none!important;scroll-behavior:auto!important;transition:none!important}}
.preflight{margin:17px 0;padding:18px;border:1px solid var(--line);border-radius:10px;background:#f6f3ed}.preflight h3{font-size:15px;margin:0 0 8px}.preflight ul{list-style:none;padding:0;margin:12px 0}.preflight li{padding:10px 0;border-top:1px solid var(--line);overflow-wrap:anywhere}.preflight li strong{font-size:13px;font-weight:500}.preflight li p{font-size:12px;color:var(--muted);margin:4px 0}.preflight details{margin:14px 0;font-size:12px;color:var(--muted)}.preflight summary{cursor:pointer;color:var(--accent)}
.planning-choice{margin:18px 0;padding:12px 0;border-top:1px solid var(--line)}.planning-choice summary,#machine-panel>summary,.node-enrollment>summary{cursor:pointer;font-weight:600}.node-enrollment{margin-top:20px}.node-enrollment label{display:block;margin:16px 0 6px}.node-enrollment input{box-sizing:border-box;width:100%;min-width:0;padding:10px;border:1px solid var(--line);border-radius:8px;background:var(--paper);font:inherit}.machine-row,.placement-row{padding:12px 0;border-bottom:1px solid var(--line);overflow-wrap:anywhere}.machine-row button,.placement-row button{margin:6px 8px 0 0;white-space:normal}.node-enrollment>button{margin-top:10px}
.mission-graph-scroll{overflow-x:auto;max-width:100%;min-width:0;scrollbar-width:thin;overscroll-behavior-x:contain;margin:12px 0}#mission-graph{display:block;font-family:var(--font)}.mission-graph-edge{fill:none;stroke:#9c8a78;stroke-width:1.5}.mission-graph-arrow{fill:#9c8a78}.mission-graph-task{cursor:pointer;outline:none}.mission-graph-task rect{fill:var(--paper);stroke:var(--line);stroke-width:1}.mission-graph-task:hover rect,.mission-graph-task:focus-visible rect{fill:var(--wash);stroke:var(--accent);stroke-width:2}.mission-graph-task text{fill:var(--ink);font-size:11px}.mission-graph-task .graph-name{font-size:13px;font-weight:500}.mission-graph-task .graph-id,.mission-graph-task .graph-scope{fill:var(--muted)}.mission-graph-task.graph-running rect{fill:#f6eee4;stroke:#bc977d}.mission-graph-task.graph-checked rect{fill:#eef2e9;stroke:var(--good)}.mission-graph-task.graph-failed rect{stroke:var(--bad)}.mission-graph-task.graph-history rect{fill:var(--side);stroke-dasharray:4 3}
.engineering-result{min-width:0;max-width:100%}.engineering-result p,.engineering-result summary,.engineering-result h4{overflow-wrap:anywhere;word-break:break-word}.engineering-result details{min-width:0;max-width:100%}.engineering-result-body{min-width:0}.engineering-result-body h4{font-size:14px;font-weight:500;margin:14px 0 6px}.engineering-evidence{font-size:12px;color:var(--muted);padding:10px 0 4px}.engineering-evidence p{margin:5px 0;white-space:pre-wrap}
</style>
</head>
<body>
<div class="app">
<aside class="sidebar" id="sidebar" aria-label="对话与任务">
  <div class="brand"><span class="brand-mark" aria-hidden="true">✳</span><div><div class="brand-name">Sisyfus</div><div class="brand-caption">想清楚，再一起做。</div></div><button class="icon-button sidebar-close" id="sidebar-close" aria-label="关闭侧栏">×</button></div>
  <button class="new-chat" id="new-chat"><span aria-hidden="true">+</span><span>新对话</span></button>
  <nav class="nav-scroll" aria-label="历史记录">
    <h2 class="nav-heading">最近对话</h2><div id="chat-list"><p class="nav-empty">正在读取对话…</p></div>
    <h2 class="nav-heading missions-heading">正在推进的任务</h2><div id="mission-list"><p class="nav-empty">正在读取任务…</p></div>
    <p class="nav-empty error" id="inventory-error" hidden></p>
    <button class="text-button small" id="inventory-retry" hidden>重新读取列表</button>
  </nav>
  <footer class="sidebar-footer"><a href="/console">开发者视图 ↗</a><button class="text-button" id="open-debug">诊断信息</button></footer>
</aside>
<main class="workspace" id="workspace">
  <header class="topbar">
    <div class="flex min-zero"><button class="icon-button mobile-menu" id="menu-toggle" aria-label="打开对话与任务列表" aria-expanded="false" aria-controls="sidebar">☰</button><div class="topbar-title"><span id="view-title">与技术负责人对话</span><span class="topbar-subtitle" id="view-subtitle">先聊清目标，开工由你决定</span></div></div>
    <div class="topbar-actions"><div class="connection" id="connection" role="status"><span id="connection-text">连接中</span></div><button class="settings-trigger" id="open-settings" aria-controls="settings" aria-expanded="false">工程与验收</button></div>
  </header>
  <div class="global-note" id="network-note" role="status" hidden><p id="network-text"></p><button class="text-button" id="reconnect">重新连接</button></div>
  <div class="global-note" id="global-note" role="status" hidden><p id="global-text"></p><button class="text-button" id="ack-create" hidden>已核对列表，继续</button></div>
  <div class="scroll-area" id="scroll-area" tabindex="0" aria-label="对话与进度">
    <div class="content">
      <section class="welcome" id="welcome"><div class="welcome-symbol" aria-hidden="true">✳</div><h1>把想法说出来，<br>我们一起把它做成。</h1><p class="welcome-intro">从一个问题、一段需求，或还没想清楚的点子开始。先一起梳理，再把方案拆成可验收的工作。</p><div class="suggestions" aria-label="试着这样开始"><button class="suggestion" data-prompt="我有一个产品想法，想和你一起梳理需求与实现方案。">聊聊我的产品想法</button><button class="suggestion" data-prompt="帮我检查现有工程，先讨论问题和验收标准，再决定如何修改。">一起看清工程里的问题</button><button class="suggestion" data-prompt="我想把一个目标拆成具体任务，请先帮我明确交付物和验收条件。">把目标拆成可验收的任务</button></div><p class="welcome-footnote">讨论不会自动开工。每次执行都需要你的明确确认。</p></section>
      <div id="load-state" class="waiting" role="status" hidden>正在读取这段记录…</div>
      <section id="load-error" class="notice error" role="alert" hidden><p id="load-error-text"></p><button class="text-button" id="load-retry">重新读取</button></section>
      <div id="chat-view" hidden>
        <section id="messages" role="log" aria-label="对话记录" aria-live="polite" aria-relevant="additions text"></section>
        <div class="waiting" id="waiting" role="status" hidden><span class="waiting-dots" aria-hidden="true"><i></i><i></i><i></i></span><span id="waiting-text">正在思考，回复会出现在这里…</span></div>
        <section class="notice" id="chat-note" role="status" hidden><p id="chat-note-text" class="prose"></p><button class="text-button" id="context-action">设置工程与验收</button><button class="text-button" id="uncertain-refresh" hidden>查询最新记录</button><button class="text-button" id="uncertain-ack" hidden>已核对记录，继续讨论</button><button class="text-button" id="chat-placement-retry" type="button" hidden>明确重试原规划请求</button></section>
        <article class="proposal" id="proposal" aria-label="待确认方案草案" hidden><div class="draft-label">方案草案 · 尚未执行或验收</div><div id="proposal-body"></div></article>
        <section class="proposal-actions" id="proposal-actions" hidden><p class="small muted" id="readiness-note"></p><button class="primary" id="review-plan" aria-controls="preflight" aria-expanded="false">检查并准备开工</button>
        <section class="preflight" id="preflight" aria-labelledby="preflight-title" hidden>
          <h3 id="preflight-title" tabindex="-1">开工准备清单</h3>
          <p class="small" id="preflight-summary"></p>
          <ul id="preflight-requirements"></ul>
          <p class="small muted" id="preflight-note"></p>
          <details id="acceptance-help"><summary>文字验收已经聊好了，为什么还要准备？</summary><p>文字验收说明“做成什么样”；固定检查说明“如何验证通过或失败”。依据上方逐项验收编写校验脚本，把检查、通过/失败条件和执行范围写入工程验收文件，经你审阅后绑定。</p><p>这是工程准备步骤，不是让你重新讲一遍需求。当前聊天尚未接入自动生成这些文件的流程；如果指标还写着“约定阈值”，需先确认具体数值。不要复用其他无关工程的检查来凑开工条件。</p><p>绑定新工程或验收文件会保留聊天记录、撤下旧方案；随后请 Opus 基于新上下文重新核对方案。</p></details>
          <div class="flex wrap"><button class="primary" id="prepare-directory" type="button" hidden>按聊天准备目录</button><button class="secondary" id="preflight-settings" type="button">查看工程与验收设置</button></div>
        </section><button class="text-button" id="linked-mission" hidden>查看任务进度 →</button>
          <form class="confirmation" id="chat-confirm" hidden><h3>这次开工的范围</h3><dl id="chat-confirm-context"></dl><button type="button" class="text-button small" id="open-confirm-plan" aria-controls="full-proposal">查看本次确认的完整方案与验收</button><label class="permission"><input type="checkbox" id="chat-permission"><span>我允许这项任务在本机执行<small>本地工作进程将使用当前用户的访问权限，读取或修改工程、运行命令，并可能产生模型调用费用。</small></span></label><details class="planning-choice"><summary>先拆分子任务，再选择执行机器</summary><label class="permission"><input type="checkbox" id="chat-planning-permission"><span>我只允许 Opus 规划并固定子任务<small>使用当前已审阅的工程与固定验收，可能产生规划调用费用。此许可不启动 Sol；选择机器后，Start 仍需单独确认。</small></span></label><button class="secondary" type="button" id="chat-prepare-placement" disabled>确认规划，准备选择机器</button><p class="small muted">ACK 仅是受理，准备状态以任务读回为准。</p></details><p class="small muted">方案仅是草案；最终结果以固定验收、独立审查与集成证据为准。</p><div class="flex wrap"><button class="primary" id="chat-start" type="submit" disabled>确认方案并开工</button><button class="text-button" id="cancel-chat-start" type="button">再想一想</button></div></form>
        </section>
      </div>
      <section id="mission-view" hidden aria-label="任务进度"><div class="flex wrap"><span class="mission-kicker">执行记录</span><button class="text-button small" id="back-to-chat" hidden>← 返回方案对话</button></div><h1 class="mission-title" id="mission-title"></h1><details class="full-proposal"><summary>完整批准目标与方案</summary><div id="mission-objective" class="small prose"></div></details><div class="mission-report" role="status"><h2 id="mission-status"></h2><p id="mission-reason" class="prose"></p><p id="acceptance-status"></p></div><div class="mission-toolbar" aria-label="任务控制"><button class="primary" id="mission-start">启动任务</button><button class="secondary" id="mission-pause">暂停派发</button><button class="secondary" id="mission-resume">恢复派发</button><button class="secondary danger-button" id="mission-stop">停止任务</button><button class="text-button" id="mission-refresh">刷新进度</button></div><p class="small muted" id="control-note" role="status"></p>
        <form id="mission-confirm" class="confirmation" hidden><h3>确认启动这项任务</h3><p class="small muted">按控制器已固定的机器执行；未选择的子任务仍使用原默认本机。远端权限与模型费用须另行确认，登记或选择机器不构成执行许可。</p><dl id="mission-confirm-context"></dl><label class="permission"><input type="checkbox" id="mission-permission"><span>我允许这项任务在本机执行<small>使用当前用户的访问权限，读取或修改工程、运行命令，并可能产生模型调用费用。</small></span></label><div class="flex wrap"><button class="primary" type="submit" id="mission-start-confirm" disabled>允许本地执行并启动</button><button class="text-button" type="button" id="cancel-mission-start">取消</button></div></form>
        <div id="stop-confirm" class="stop-note" hidden><p>停止是协作式请求。正在执行的调用可能仍在收尾；停止后不会自动重新开工。</p><div class="flex"><button class="secondary danger-button" id="confirm-stop">确认停止</button><button class="text-button" id="cancel-stop">取消</button></div></div>
        <section class="mission-section" aria-labelledby="mission-conversation-title"><h3 id="mission-conversation-title">任务对话</h3><p class="small muted">输入 /btw 或 /btw 问题，读取控制器状态；普通文字作为补充资料。消息不启动工作，也不修改已批准目标或固定验收。</p><div id="mission-message-thread" role="log" aria-label="任务查询与补充资料记录" aria-live="polite" aria-relevant="additions text"></div><p id="mission-inbox-note" class="small prose" role="status"></p><div class="flex wrap"><button class="text-button small" id="mission-inbox-refresh">查询消息与应用回执</button><button class="text-button small" id="mission-inbox-retry" hidden>用原请求编号重试提交</button></div></section>
        <section class="mission-section" aria-labelledby="mission-graph-title"><h3 id="mission-graph-title">任务依赖图</h3><p id="mission-graph-help" class="small muted">固定依赖从左到右。点击任务或按 Enter / 空格，查看下方原验收详情。执行、检查与审查分开记录；整项结论以上方核心读回为准。</p><div id="mission-graph-scroll" class="mission-graph-scroll"><svg id="mission-graph" xmlns="http://www.w3.org/2000/svg" role="img" aria-labelledby="mission-graph-title" aria-describedby="mission-graph-help mission-graph-note"></svg></div><p id="mission-graph-note" class="small prose" role="status">正在读取固定任务图。</p></section>
        <section class="mission-section engineering-result" id="engineeringResult" aria-labelledby="engineeringResultTitle"><h3 id="engineeringResultTitle">工程结果 · 捕获投影，非验收</h3><p id="engineeringResultStatus" class="small prose muted" role="status" aria-live="polite">正在读取工程结果。</p><div id="engineeringResultBody" class="engineering-result-body"></div></section>
        <details class="mission-section" id="machine-panel" hidden><summary>执行机器与固定选择</summary><p class="small prose" id="machine-note" role="status"></p><button type="button" class="secondary small" id="machine-retry" aria-describedby="machine-note" hidden disabled>明确重试原机器请求</button><div id="machine-list"></div><h3>固定子任务的执行位置</h3><div id="placement-list"></div>
          <details class="node-enrollment"><summary>登记一台机器 · 仅配置，不执行</summary><label for="node-name">机器名称</label><input id="node-name" type="text" autocomplete="off" placeholder="例如：研究用 Mac"><button class="secondary" type="button" id="node-enroll" disabled>明确登记机器</button><p class="small muted">登记不代表在线或原生登录。首次凭据仅在本页内存；刷新或首次响应丢失后，请撤销并重新明确登记。</p>
            <label for="node-gateway-url">NodeAgent 连接地址（明确填写 loopback）</label><input id="node-gateway-url" type="text" autocomplete="off" inputmode="url" placeholder="http://127.0.0.1:连接端口">
            <label for="node-gateway-host">网关固定 Host（明确填写实际 Host）</label><input id="node-gateway-host" type="text" autocomplete="off" placeholder="127.0.0.1:实际网关端口"><p class="small muted">SSH 本地转发端口可以不同；这里不猜测网页端口，也不建立 SSH。保存 credential 文件权限为 0600，state 目录为 0700。</p><div class="flex wrap"><button class="secondary" id="node-config-copy" type="button" disabled>明确复制首次配置</button><button class="text-button" id="node-config-download" type="button" disabled>明确下载首次配置</button></div>
          </details></details><section class="mission-section"><h3>工作拆解</h3><div id="task-list"></div></section><section class="mission-section"><h3>诊断、验收与集成</h3><div id="progress-thread"></div></section><section class="mission-section" aria-labelledby="rsi-evidence-title"><h3 id="rsi-evidence-title">RSI 对照与晋升</h3><div id="rsi-evidence"></div></section><section class="mission-section" id="event-section" hidden><h3>最近动态</h3><div id="event-thread"></div></section><button class="text-button small" id="mission-debug">查看原始证据与控制记录 →</button>
      </section>
    </div>
  </div>
  <button class="jump-latest" id="jump-latest" hidden>↓ 最新消息</button>
  <div class="composer-wrap" id="composer-wrap"><form class="composer" id="composer-form"><label class="sr-only" for="composer-input">你想一起做什么？</label><textarea id="composer-input" rows="2" placeholder="你想一起做什么？" autocomplete="off" aria-describedby="composer-help"></textarea><div class="composer-footer"><button class="composer-context" id="composer-settings" type="button">＋ 设置工程与验收</button><button class="send" id="send" type="submit" aria-label="发送消息" disabled>↑</button></div></form><div class="composer-hint" id="composer-help"><span id="model-label">先讨论，确认后才执行</span><span>Enter 发送 · Shift + Enter 换行</span></div></div>
</main>
</div>
<button class="backdrop" id="backdrop" aria-label="关闭抽屉" tabindex="-1" hidden></button>
<aside class="drawer" id="settings" role="dialog" aria-modal="true" aria-labelledby="settings-title" hidden><header class="drawer-header"><h2 id="settings-title">工程与验收</h2><button class="icon-button" id="close-settings" aria-label="关闭工程设置">×</button></header><div class="drawer-body"><p class="drawer-intro" id="settings-intro">先聊想法也可以。开工前，再绑定工程和已经批准的验收文件。</p><section id="reuse-project"><label class="field" for="existing-project">选择已有工程<select id="existing-project"><option value="">选择一个工程与验收方案…</option></select><small>按任务目标选择已批准的工程。不复用旧结果，也不会启动已有任务。</small></label><button class="primary" id="attach-mission" disabled>复用工程与验收</button><p class="small muted" id="attach-state" role="status"></p></section><details class="settings-section" id="manual-context"><summary>手动填写工程路径</summary><form id="context-form"><label class="field" for="source">工程目录<input id="source" type="text" placeholder="/Users/you/projects/my-project" autocomplete="off" spellcheck="false"><small>也可以直接在聊天里要求创建或设置目录，系统会检查并准备；此处保留手动绑定入口。</small></label><label class="field" for="spec-path">验收文件<input id="spec-path" type="text" placeholder="/Users/you/specs/approved.json" autocomplete="off" spellcheck="false"><small>工程准备阶段产出的已批准验收文件（spec）的绝对路径。聊天中的文字验收不等于固定检查，尚未自动生成此文件。</small></label><div class="form-actions"><button class="primary" type="submit" id="save-context">保存设置</button><span class="small muted" id="context-save-state" role="status"></span></div><p class="small error prose" id="context-error" role="alert" hidden></p></form></details><details class="settings-section"><summary>已绑定的验收条件</summary><div id="context-checks"><p class="small muted">尚未绑定验收文件。</p></div></details><details class="settings-section"><summary>模型与执行说明</summary><div class="stack small muted"><p id="settings-model">尚无运行模型记录。</p><p>默认请求模型：负责人、独立审查使用 claude-opus-5-5；实施使用 gpt-6.1-sol。实际模型以运行回执为准。</p><p>总预算：Unlimited（默认不设总量上限）</p><p>已绑定任务的实际预算以核心记录为准；单次调用超时、并行限制与人工停止仍然生效。</p><p>对话与方案不会派发工作。开工时单独确认本地执行许可。</p><p>收到控制请求、模型返回或单项检查通过，都不等于整项任务已验收。</p><button class="text-button" id="settings-debug" type="button">打开诊断信息</button><a href="/console">旧版开发者控制台 ↗</a></div></details></div></aside>
<aside class="drawer" id="debug" role="dialog" aria-modal="true" aria-labelledby="debug-title" hidden><header class="drawer-header"><h2 id="debug-title">诊断信息</h2><button class="icon-button" id="close-debug" aria-label="关闭诊断信息">×</button></header><div class="drawer-body"><p class="drawer-intro">只读原始记录。控制 ACK 仅表示请求已接收，验收以核心快照为准。访问令牌不会显示在这里。</p><details class="debug-block"><summary>当前对话 / 核心快照</summary><pre id="debug-state"></pre></details><details class="debug-block"><summary>任务事件</summary><pre id="debug-events"></pre></details><details class="debug-block"><summary>控制请求记录</summary><pre id="debug-controls"></pre></details><details class="debug-block"><summary>连接与请求诊断</summary><pre id="debug-requests"></pre></details><details class="debug-block"><summary>列表读取问题</summary><pre id="debug-issues"></pre></details><a href="/console">打开旧版开发者视图 ↗</a></div></aside>
<div class="sr-only" role="status" aria-live="polite" id="announcement"></div>
<script nonce="NONCE">
'use strict';
const $ = id => document.getElementById(id);
const storageKey = 'sisyfus-techlead:' + location.origin;
let token = new URLSearchParams(location.hash.slice(1)).get('token') || '';
let storageIssue = '';
try {
  token = token || sessionStorage.getItem(storageKey) || '';
  if (token) sessionStorage.setItem(storageKey, token);
} catch (error) { storageIssue = '浏览器会话存储不可用；刷新后请使用原始访问入口。'; }
history.replaceState(null, '', location.pathname + location.search);
const state = {
  kind: 'welcome', id: '', epoch: 0, version: 0, chat: null, mission: null, engineering: null, engineeringRead: null,
  chats: [], missions: [], issues: [], chatIssues: [], chatsLoaded: false, inventoryLoaded: false, inventoryError: '',
  loading: false, loadError: '', connected: false, networkError: '', lastRead: null,
  busy: null, cursor: 0, events: [], traces: [], drafts: new Map(), pending: new Map(), inboxes: new Map(), machines: new Map(), missionChats: new Map(),
  signatures: new Map(), drawer: null, returnFocus: null, contextDirty: false,
  contextOwner: '', contextValues: {source: '', spec_path: ''}, contextEpoch: 0,
  controlNote: '', chatNotice: '', forceScroll: false, composing: false,
  confirmFingerprint: '', confirmedApprovalHash: null, missionConfirmFingerprint: '', inventoryAt: 0
};
// Credential responses never enter state, DOM, storage, request traces or debug.
// Only the two explicit export actions can read this private page-lifetime map.
const nodeCredentials = new Map();
const nodeSecretRedactions = new Set(); // Revocation removes export, not redaction.
const machineTransports = new Map(); // Ephemeral key -> exact operation; never persist a transport hold.
try {
  const saved = JSON.parse(sessionStorage.getItem(storageKey + ':pending') || '[]');
  if (Array.isArray(saved)) for (const [key, value] of saved) {
    if (typeof key === 'string' && value && typeof value.type === 'string') state.pending.set(key, value);
  }
} catch (error) { storageIssue = storageIssue || '待确认请求记录读取失败，请先核对历史记录。'; }
function persistPending() {
  try { sessionStorage.setItem(storageKey + ':pending', JSON.stringify([...state.pending])); }
  catch (error) { storageIssue = '待确认请求只保存在本页；请先核对结果，再刷新页面。'; }
}
function setPending(key, value) { state.pending.set(key, value); persistPending(); }
function clearPending(key) { state.pending.delete(key); persistPending(); }
function pendingKey() { return state.kind + ':' + state.id; }
function clean(value) {
  let content = (typeof value === 'string' ? value : JSON.stringify(value, null, 2)) || '';
  if (token) content = content.split(token).join('[已隐藏凭据]');
  for (const secret of nodeSecretRedactions) content = content.split(secret).join('[已隐藏凭据]');
  return content.replace(/\bNode\s+[a-f0-9]{64}\b/gi,'Node [已隐藏凭据]');
}
function text(value) { return typeof value === 'string' || typeof value === 'number' ? String(value) : ''; }
function array(value) { return Array.isArray(value) ? value : []; }
function previewText(value, limit = 110) {
  const content = text(value).trim().replace(/\s+/g,' '), chars = Array.from(content);
  return chars.length > limit ? chars.slice(0,limit).join('') + '…' : content;
}
function node(tag, content, className) {
  const item = document.createElement(tag);
  if (content !== undefined) item.textContent = text(content);
  if (className) item.className = className;
  return item;
}
function say(message) { $('announcement').textContent = message; }
function showGlobal(message, acknowledge = false) {
  $('global-note').hidden = !message; $('global-text').textContent = message;
  $('ack-create').hidden = !acknowledge;
}
function trace(row) {
  state.traces.push(row); state.traces = state.traces.slice(-35);
  if (state.drawer === 'debug') renderDebug();
}
class RequestError extends Error {
  constructor(message, uncertain = false, status = 0) { super(message); this.uncertain = uncertain; this.status = status; }
}
async function api(path, body, timeoutMs, extraHeaders = {}) {
  const post = body !== undefined;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs ?? (post ? 25000 : 14000));
  const started = Date.now();
  let status = 0;
  try {
    const response = await fetch(path, {
      method: post ? 'POST' : 'GET', cache: 'no-store', credentials: 'same-origin',
      signal: controller.signal,
      headers: {Authorization: 'Bearer ' + token, ...extraHeaders, ...(post ? {'Content-Type': 'application/json'} : {})},
      body: post ? JSON.stringify(body) : undefined
    });
    status = response.status;
    let data;
    try { data = await response.json(); }
    catch (error) { throw new RequestError('服务返回了未识别的内容，请查询最新状态。', post, status); }
    if (!response.ok) {
      const detail = typeof data.error === 'string' ? data.error : data.error?.message;
      const message = status === 401 || status === 403
        ? '访问验证未通过。请从含访问令牌的入口重新打开。'
        : '请求未成功' + (detail ? '：' + clean(detail) : '（HTTP ' + status + '）');
      throw new RequestError(message, post && status >= 500, status);
    }
    trace({method: post ? 'POST' : 'GET', path, status, duration_ms: Date.now() - started, request_id: body?.request_id || null});
    return data;
  } catch (error) {
    const failure = error instanceof RequestError ? error : new RequestError(
      error.name === 'AbortError' ? '等待服务响应超时。' : '连接中断，请检查本地服务或网络。', post, status);
    trace({method: post ? 'POST' : 'GET', path, status, duration_ms: Date.now() - started,
      request_id: body?.request_id || null, uncertain: failure.uncertain, error: clean(failure.message)});
    throw failure;
  } finally { clearTimeout(timer); }
}
function requestId() {
  if (!globalThis.crypto?.randomUUID) throw new RequestError('此浏览器缺少请求编号支持，请使用本机 localhost 页面或更新浏览器。');
  return crypto.randomUUID();
}
const labels = {
  IDLE:'等待讨论', RUNNING:'正在处理', STARTING:'正在准备开工', ERROR:'出现问题', UNKNOWN:'结果待确认',
  PLANNING:'正在梳理实施方案', WAITING_PLACEMENT:'子任务已准备，等待选择执行机器', EXECUTING:'正在实施', VERIFYING:'正在验收', REVIEWING:'正在独立审查',
  INTEGRATING:'正在集成验证', IMPLEMENTING:'正在实施', DIAGNOSING:'正在诊断', WAITING_LEAD:'等待负责人继续分析', NEEDS_OPERATOR:'需要你确认下一步',
  PAUSED:'已暂停新工作派发', STOPPED:'任务已停止', STALE:'验收证据需要更新',
  TRIAL_RUNNING:'正在评估流程改进', TRIAL_FENCED:'流程评估已被隔离',
  COMPLETED:'执行已返回，等待验收确认', SUCCEEDED:'执行已返回', FAILED:'执行遇到问题',
  PENDING:'等待执行', ADMITTING:'等待派发', READY:'准备执行', IN_FLIGHT:'调用进行中',
  RETRYABLE:'等待调整后继续', BLOCKED:'等待前置条件', UNVERIFIED:'尚未验收',
  PASS:'验收通过', FAIL:'验收未通过', INVALID:'证据无效', CANCELLED:'已取消',
  ACK:'控制请求已接收', specification:'需求', architecture:'架构', dependency:'依赖',
  implementation:'实现', environment:'环境', integration:'集成'
};
function label(value, fallback = '等待状态更新') { return labels[value] || (value ? '状态：' + text(value) : fallback); }
function briefDate(value) {
  if (!value) return '';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? '' : date.toLocaleDateString('zh-CN', {month:'numeric', day:'numeric'});
}
function paint(id, value, build) {
  const signature = JSON.stringify(value);
  if (state.signatures.get(id) === signature) return false;
  state.signatures.set(id, signature);
  const root = $(id);
  const open = new Set([...root.querySelectorAll('details[open]')].map(item => item.dataset.detail));
  const focused = root.contains(document.activeElement) ? document.activeElement.dataset.focus : null;
  const children = build();
  root.replaceChildren(...children);
  for (const item of root.querySelectorAll('details')) if (open.has(item.dataset.detail)) item.open = true;
  if (focused) for (const item of root.querySelectorAll('[data-focus]')) {
    if (item.dataset.focus === focused) item.focus({preventScroll:true});
  }
  return true;
}
function renderLists() {
  paint('chat-list', [state.chats, state.kind, state.id, state.inventoryLoaded], () => {
    if (!state.chats.length) return [node('p', state.inventoryLoaded ? '从新对话开始，记录会留在这里。' : '正在读取对话…', 'nav-empty')];
    return state.chats.map(chat => {
      const button = node('button', undefined, 'nav-item');
      button.setAttribute('aria-current', String(state.kind === 'chat' && state.id === chat.id));
      button.dataset.focus = 'chat-' + chat.id;
      button.title = chat.title || '新的对话';
      button.setAttribute('aria-label','对话：' + button.title);
      button.append(node('span', previewText(chat.title || '新的对话',32), 'nav-title'), node('span',
        [chat.mission_id ? '已关联任务' : label(chat.status), briefDate(chat.updated_at)].filter(Boolean).join(' · '), 'nav-meta'));
      button.onclick = () => selectChat(chat.id);
      return button;
    });
  });
  paint('mission-list', [state.missions, state.kind, state.id, state.inventoryLoaded], () => {
    if (!state.missions.length) return [node('p', state.inventoryLoaded ? '确认开工后，在这里跟进进度。' : '正在读取任务…', 'nav-empty')];
    return state.missions.map(mission => {
      const button = node('button', undefined, 'nav-item');
      button.setAttribute('aria-current', String(state.kind === 'mission' && state.id === mission.id));
      button.dataset.focus = 'mission-' + mission.id;
      button.title = mission.objective || mission.id;
      button.setAttribute('aria-label','任务：' + button.title);
      button.append(node('span', previewText(mission.objective || '已批准的工程',40), 'nav-title'), node('span',
        mission.controller_running ? '控制器正在运行 · 验收另行确认' : '查看进度与验收', 'nav-meta'));
      button.onclick = () => selectMission(mission.id);
      return button;
    });
  });
  $('inventory-error').hidden = !state.inventoryError;
  $('inventory-error').textContent = state.inventoryError;
  $('inventory-retry').hidden = !state.inventoryError;
  $('new-chat').disabled = !!state.busy || state.pending.has('create');
}
let inventoryPromise = null;
async function inventory() {
  if (inventoryPromise) return inventoryPromise;
  state.chatsLoaded = false; // Stale/initial rows never prove that a mission is unlinked.
  if (state.kind === 'mission') renderControlAvailability();
  inventoryPromise = (async () => {
    const results = await Promise.allSettled([api('/api/chats'), api('/api/missions')]);
    const errors = [];
    const chatList = results[0].status === 'fulfilled' ? results[0].value : null;
    if (Array.isArray(chatList?.chats) && chatList.chats.every(chat => chat && typeof chat.id === 'string' && chat.id &&
        (chat.mission_id == null || typeof chat.mission_id === 'string' && chat.mission_id)) &&
        new Set(chatList.chats.map(chat => chat.id)).size === chatList.chats.length) {
      state.chats = chatList.chats; state.chatIssues = array(chatList.issues);
      // Older inventory projections omit issues. A present malformed field is
      // not an empty list, and local upserts never establish this HTTP proof.
      state.chatsLoaded = (chatList.issues === undefined || Array.isArray(chatList.issues)) && !state.chatIssues.length;
      if (state.chatIssues.length) errors.push('有 ' + state.chatIssues.length + ' 段对话记录不完整，其他对话可继续使用');
      else if (!state.chatsLoaded) errors.push('对话库存格式异常，请重新查询核对关联。');
    }
    else errors.push('对话列表暂未读到');
    if (results[1].status === 'fulfilled' && Array.isArray(results[1].value.missions)) {
      state.missions = results[1].value.missions; state.issues = array(results[1].value.issues);
      if (state.issues.length) errors.push('有 ' + state.issues.length + ' 项记录读取异常，详情见诊断');
    } else errors.push('任务列表暂未读到');
    state.inventoryLoaded = true; state.inventoryError = errors.join('；'); state.inventoryAt = Date.now();
    if (results.every(result => result.status === 'rejected')) networkFailure(results[0].reason.message);
    else if (state.kind === 'welcome') networkSuccess();
    renderLists(); if (state.drawer === 'settings') renderExistingProjects(); if (state.drawer === 'debug') renderDebug();
    if (state.kind === 'mission') renderControlAvailability();
  })().finally(() => { inventoryPromise = null; });
  return inventoryPromise;
}
function networkFailure(message) {
  state.connected = false; state.networkError = clean(message); renderConnection(); renderAvailability();
}
function networkSuccess() {
  state.connected = true; state.networkError = ''; state.lastRead = new Date().toISOString(); renderConnection();
}
function renderConnection() {
  $('connection').classList.toggle('offline', !state.connected);
  $('connection-text').textContent = state.connected ? '已连接' : (state.networkError ? '连接待恢复' : '连接中');
  $('network-note').hidden = !state.networkError;
  $('network-text').textContent = state.networkError + ' 已显示的内容可能不是最新状态；恢复后只查询，不重发请求。';
}
function draftKey(kind = state.kind, id = state.id) { return kind + ':' + id; }
function saveDraft() { state.drafts.set(draftKey(), $('composer-input').value); }
function resizeComposer() {
  const input = $('composer-input'); input.style.height = 'auto';
  input.style.height = Math.min(180, Math.max(48, input.scrollHeight)) + 'px';
}
function switchView(kind, id) {
  saveDraft(); closeDrawer(false); state.kind = kind; state.id = id; state.epoch++; state.version++;
  try { sessionStorage.setItem(storageKey + ':view',JSON.stringify({kind,id})); }
  catch (error) { storageIssue = '当前页面选择只保存在本页；刷新后请从侧栏选择任务。'; }
  state.chat = null; state.mission = null; state.engineering = null; state.engineeringRead = null; state.loadError = ''; state.loading = true;
  state.cursor = 0; state.events = []; state.controlNote = ''; state.chatNotice = '';
  state.contextOwner = ''; state.contextDirty = false; state.contextEpoch++;
  state.confirmFingerprint = ''; state.confirmedApprovalHash = null; state.missionConfirmFingerprint = '';
  $('preflight').hidden = true; $('review-plan').setAttribute('aria-expanded','false');
  $('chat-confirm').hidden = true; $('chat-permission').checked = false; $('chat-planning-permission').checked = false;
  $('node-name').value = ''; $('node-gateway-url').value = ''; $('node-gateway-host').value = '';
  $('mission-confirm').hidden = true; $('mission-permission').checked = false; $('stop-confirm').hidden = true;
  $('composer-input').value = state.drafts.get(draftKey()) || ''; resizeComposer();
  state.forceScroll = kind === 'chat'; render(); $('scroll-area').scrollTop = 0;
}
async function selectChat(id) { switchView('chat', id); await readSelected(); }
async function selectMission(id) { switchView('mission', id); await readSelected(); }
async function restoreSelectedView() {
  try {
    const selected = JSON.parse(sessionStorage.getItem(storageKey + ':view') || 'null');
    if (selected && ['chat','mission'].includes(selected.kind) && typeof selected.id === 'string' && selected.id) {
      switchView(selected.kind,selected.id); await readSelected();
    }
  } catch (error) { showGlobal('上次页面选择读取失败，请从侧栏重新选择。' + clean(error.message)); }
}
function upsertChat(chat) {
  const summary = {id:chat.id,title:chat.title,status:chat.status,mission_id:chat.mission_id,updated_at:chat.updated_at};
  const index = state.chats.findIndex(item => item.id === chat.id);
  if (index < 0) state.chats.unshift(summary); else state.chats[index] = summary;
}
function validateChat(chat, id, uncertain = false) {
  if (!chat || typeof chat.id !== 'string' || (id && chat.id !== id) || !Array.isArray(chat.messages)) {
    throw new RequestError('对话记录格式不完整，请重新读取。', uncertain);
  }
  return chat;
}
function reconcileChat(chat) {
  const key = 'chat:' + chat.id, pending = state.pending.get(key);
  if (!pending) return;
  if (pending.type === 'start' && chat.mission_id) clearPending(key);
  if (pending.type === 'prepare-placement' && matchingPreparation(chat,pending)) clearPending(key);
  if (pending.type === 'directory' && chat.directory_preparation?.request_id === pending.request_id && chat.directory_preparation.status !== 'PREPARING') clearPending(key);
  if (pending.type === 'context' && chat.source === pending.source && chat.spec_path === pending.spec_path) clearPending(key);
  if (pending.type === 'attach' && chat.source === pending.source && chat.spec_path && chat.spec_path !== pending.before_spec) clearPending(key);
  if (pending.type === 'message') {
    const newUserIndex = chat.messages.findIndex(message => message.role === 'user' && message.id && !array(pending.before).includes(message.id));
    if (newUserIndex >= 0 && (chat.status === 'ERROR' || chat.status === 'IDLE' && chat.messages.slice(newUserIndex + 1).some(message => message.role === 'assistant'))) clearPending(key);
  }
}
function applyChat(chat) {
  state.chat = chat; upsertChat(chat); reconcileChat(chat); render(); syncSettings(false);
}
let readSerial = 0;
async function readSelected() {
  if (state.kind === 'welcome' || !state.id) return;
  const kind = state.kind, id = state.id, epoch = state.epoch, version = state.version, serial = ++readSerial;
  const current = () => state.kind === kind && state.id === id && state.epoch === epoch && state.version === version && readSerial === serial;
  const engineeringRead = kind === 'mission' ? {id,epoch,version,serial} : null;
  if (engineeringRead) { state.engineeringRead = engineeringRead; $('engineeringResult').hidden = true; }
  try {
    if (kind === 'chat') {
      const chat = validateChat(await api('/api/chat?chat_id=' + encodeURIComponent(id)), id);
      if (!current()) return;
      state.loading = false; state.loadError = ''; networkSuccess(); applyChat(chat);
    } else {
      // Independent incremental streams also observe changes to older applications.
      // Start it independently of snapshot/events so one failed channel cannot hide another.
      const inboxRead = readMissionInbox(id,current);
      const machineRead = readMachines(id,current);
      const missionChatRead = readMissionChat(id,current);
      const independentReads = Promise.allSettled([inboxRead,machineRead,missionChatRead]);
      try {
        const data = await api('/api/snapshot?mission_id=' + encodeURIComponent(id), undefined, undefined, {'X-Sisyfus-Engineering-Result':'1'});
        if (!data || !data.snapshot || typeof data.snapshot !== 'object' || !data.controller) throw new RequestError('任务快照格式不完整，请重新读取。');
        if (!current()) return;
        const hasId = Object.prototype.hasOwnProperty.call(data,'id'), hasResult = Object.prototype.hasOwnProperty.call(data,'engineering_result');
        if ((hasId && data.id !== id) || (!hasId && hasResult)) throw new RequestError('任务快照与所选任务不一致，已拒绝显示。');
        const engineering = classifyEngineering(data,id);
        state.mission = data; state.engineering = {owner:id,epoch,...engineering,stale:false};
        state.loading = false; state.loadError = ''; reconcileControl(data); networkSuccess(); render(); syncSettings(false);
        await inboxRead;
        await machineRead;
        await missionChatRead;
        if (!current()) return;
        const batch = await api('/api/events?mission_id=' + encodeURIComponent(id) + '&cursor=' + encodeURIComponent(state.cursor));
        if (!current()) return;
        if (!Array.isArray(batch.events) || !Number.isInteger(batch.cursor) || batch.cursor < state.cursor) throw new RequestError('任务事件游标异常，请重新读取。');
        const seen = new Set(state.events.map(event => event.seq));
        state.events.push(...batch.events.filter(event => !seen.has(event.seq)));
        state.events = state.events.slice(-160); state.cursor = batch.cursor; renderEvents();
      } finally {
        // Even an early capture failure must let the independent Core paints settle first.
        const failed = (await independentReads).find(read => read.status === 'rejected');
        if (failed) throw failed.reason;
      }
    }
  } catch (error) {
    if (!current()) return;
    if (kind === 'mission' && state.engineering?.owner === id && state.engineering.epoch === epoch) state.engineering = {...state.engineering,stale:true};
    state.loading = false; state.loadError = clean(error.message); networkFailure(error.message); render();
  } finally {
    if (engineeringRead && state.engineeringRead === engineeringRead) {
      state.engineeringRead = null;
      if (current()) renderEngineeringResult();
    }
  }
}
// Validate the frozen S0 wire for presentation, never for acceptance or runtime truth.
function engineeringObject(value, keys, optional = []) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
  const prototype = Object.getPrototypeOf(value);
  if (prototype !== null && Object.getPrototypeOf(prototype) !== null) return false;
  const own = Object.keys(value);
  return keys.every(key => Object.prototype.hasOwnProperty.call(value,key)) && own.every(key => keys.includes(key) || optional.includes(key));
}
function engineeringText(value, cap = 8388608) {
  if (typeof value !== 'string' || value.length > cap) return false;
  let bytes = 0;
  for (const char of value) {
    const point = char.codePointAt(0);
    if (point >= 0xd800 && point <= 0xdfff) return false;
    bytes += point < 0x80 ? 1 : point < 0x800 ? 2 : point < 0x10000 ? 3 : 4;
    if (bytes > cap) return false;
  }
  return true;
}
function engineeringPointer(value) { return engineeringText(value) && value.startsWith('/'); }
function validEngineeringResult(result) {
  const object = engineeringObject, string = engineeringText;
  const integer = (v,max = 2 ** 63 - 1) => Number.isInteger(v) && v >= 0 && v <= max;
  const tri = v => v === null || typeof v === 'boolean';
  const list = (v,cap,check) => Array.isArray(v) && v.length <= cap && v.every(check);
  const hash = v => typeof v === 'string' && /^[0-9a-f]{64}$/.test(v);
  const tokenValue = v => typeof v === 'string' && /^[A-Z][A-Z0-9_]{0,31}$/.test(v);
  const labelValue = v => string(v) && /^[A-Z][A-Z0-9_]*$/.test(v);
  const identity = v => (string(v,256) && v.length > 0) || integer(v);
  const fact = (v,kind = 'text',objective = false) => {
    if (!object(v,['state','value','source'],['row_ordinal','utf8_bytes']) || !engineeringPointer(v.source) ||
        !['RECORDED','FILTERED','NOT_RECORDED','REDACTED_AT_CAPTURE','WITHHELD','MALFORMED'].includes(v.state)) return false;
    if ('row_ordinal' in v && !integer(v.row_ordinal)) return false;
    if ('utf8_bytes' in v && !integer(v.utf8_bytes)) return false;
    if (v.state !== 'RECORDED' && v.state !== 'FILTERED') return v.value === null;
    if (v.state === 'FILTERED') return kind === 'text' && string(v.value);
    if (kind === 'bool') return typeof v.value === 'boolean';
    if (kind === 'int') return integer(v.value);
    if (kind === 'hash') return hash(v.value);
    if (kind === 'identity') return identity(v.value);
    if (kind === 'token') return tokenValue(v.value);
    if (kind === 'id') return string(v.value,256) && v.value.length > 0;
    if (kind === 'paths' || kind === 'ids') return list(v.value,64,x => string(x,kind === 'paths' ? 1024 : 256) && x.length > 0);
    return string(v.value,objective ? 80000 : 16384) && (!objective || Array.from(v.value).length <= 20000);
  };
  const facts = (v,kinds) => Object.entries(kinds).every(([key,kind]) => fact(v[key],kind));
  let diagnosticCount = 0;
  const diagnostics = v => list(v,8192,x => {
    diagnosticCount++;
    return diagnosticCount <= 8192 && object(x,['code','section','source']) && labelValue(x.code) && string(x.section,32) && engineeringPointer(x.source);
  });
  const patch = v => object(v,['row_count','withheld_count','rows']) && integer(v.row_count,512) && integer(v.withheld_count,v.row_count) &&
    list(v.rows,512,x => object(x,['path','change_kind','before','after','source'],['row_ordinal']) &&
      (x.path === null || (string(x.path,1024) && x.path.length > 0)) &&
      ['ADDED','REMOVED','MODIFIED','REDACTED_AT_CAPTURE','WITHHELD','MALFORMED'].includes(x.change_kind) &&
      (x.before === null || hash(x.before)) && (x.after === null || hash(x.after)) && engineeringPointer(x.source) &&
      (!('row_ordinal' in x) || integer(x.row_ordinal,511))) && v.row_count === v.rows.length;
  const checkHashes = v => list(v,64,x => object(x,['check','check_hash']) && fact(x.check,'id') && fact(x.check_hash,'hash'));
  const dependencies = v => list(v,64,x => object(x,['task_id','evidence_id','matches_captured_upstream']) && fact(x.task_id,'id') && fact(x.evidence_id,'identity') && tri(x.matches_captured_upstream));
  const failure = v => object(v,['native_status','scope_error_recorded','integrity_error_recorded']) && fact(v.native_status,'token') && tri(v.scope_error_recorded) && tri(v.integrity_error_recorded);
  const deliverable = v => object(v,['candidate_location','candidate_hash','run_key','patch']) && v.candidate_location === 'WITHHELD_ABSOLUTE_LOCATOR' && fact(v.candidate_hash,'hash') && fact(v.run_key,'id') && patch(v.patch);
  const measurement = v => object(v,['scalars','execution_error_recorded','withheld_count','omitted_scalar_count','complete']) &&
    list(v.scalars,64,x => object(x,['name','value','source']) && string(x.name,1024) && engineeringPointer(x.source) &&
      (typeof x.value === 'boolean' || (typeof x.value === 'number' && Number.isFinite(x.value)))) &&
    tri(v.execution_error_recorded) && integer(v.withheld_count,4096) && integer(v.omitted_scalar_count,4096) && typeof v.complete === 'boolean';
  const checks = v => list(v,64,x => object(x,['id','check','candidate_hash','check_hash','status','summary','measurement']) &&
    facts(x,{id:'id',check:'id',candidate_hash:'hash',check_hash:'hash',status:'token',summary:'text'}) && measurement(x.measurement));
  const review = v => object(v,['recorded','verdict','reasons','candidate_hash','evidence_refs','run_key','references_cover_recorded_checks']) && typeof v.recorded === 'boolean' &&
    facts(v,{verdict:'token',candidate_hash:'hash',run_key:'id'}) && list(v.reasons,64,x => fact(x)) && list(v.evidence_refs,64,x => fact(x,'id')) && tri(v.references_cover_recorded_checks);
  const artifact = v => object(v,['deliverable','checks','review','acceptance_hash','check_hashes','dependencies','failure_indicators']) &&
    deliverable(v.deliverable) && checks(v.checks) && review(v.review) && fact(v.acceptance_hash,'hash') && checkHashes(v.check_hashes) && dependencies(v.dependencies) && failure(v.failure_indicators);
  const task = v => object(v,['task_id','objective','acceptance','check','write_paths','depends_on','workflow','currentness','deliverable','checks','review','acceptance_fingerprints','failure_indicators','uncertain_run_keys','stage','diagnostics']) &&
    facts(v,{task_id:'id',check:'id',write_paths:'paths',depends_on:'ids'}) && fact(v.objective,'text',true) && fact(v.acceptance,'text',true) && labelValue(v.stage) &&
    object(v.workflow,['state','recorded_verdict','payload_verdict','attempts','evidence_id','verification_summary']) && facts(v.workflow,{state:'token',recorded_verdict:'token',payload_verdict:'token',attempts:'int',evidence_id:'identity',verification_summary:'text'}) &&
    object(v.currentness,['active','stale','superseded_by','label']) && facts(v.currentness,{active:'bool',stale:'bool',superseded_by:'id'}) && labelValue(v.currentness.label) &&
    (v.deliverable === null || deliverable(v.deliverable)) && checks(v.checks) && review(v.review) &&
    object(v.acceptance_fingerprints,['acceptance_hash','task_hash','check_hashes','dependencies']) && facts(v.acceptance_fingerprints,{acceptance_hash:'hash',task_hash:'hash'}) && checkHashes(v.acceptance_fingerprints.check_hashes) && dependencies(v.acceptance_fingerprints.dependencies) &&
    failure(v.failure_indicators) && list(v.uncertain_run_keys,2048,x => string(x,256) && x.length > 0) && diagnostics(v.diagnostics);
  const attempt = v => object(v,['run_key','task_id','status','receipt_status','evidence_id','association','associated_task_id','unresolved','unverified_candidate','source']) &&
    facts(v,{run_key:'id',task_id:'id',status:'token',receipt_status:'token',evidence_id:'identity'}) && tokenValue(v.association) &&
    (v.associated_task_id === null || (string(v.associated_task_id,256) && v.associated_task_id.length > 0)) && typeof v.unresolved === 'boolean' && engineeringPointer(v.source) &&
    (v.unverified_candidate === null || (object(v.unverified_candidate,['candidate_hash','patch']) && fact(v.unverified_candidate.candidate_hash,'hash') && patch(v.unverified_candidate.patch)));
  const build = v => object(v,['key','created_at','status','run_key','candidate_hash','patch','dependencies','label','source']) &&
    facts(v,{key:'id',created_at:'id',status:'token',run_key:'id',candidate_hash:'hash'}) && patch(v.patch) && dependencies(v.dependencies) && v.label === 'CANDIDATE_ONLY_NOT_ACCEPTANCE' && engineeringPointer(v.source);
  if (!object(result,['schema','classification','question','conclusion','tasks','integration','attempts','control','provenance','limitations','diagnostics']) ||
      result.schema !== 'sisyfus.lead_result.engineering.s0.v1' || result.classification !== 'CAPTURED_ENGINEERING_PROJECTION_NOT_ACCEPTANCE' ||
      !engineeringText(JSON.stringify(result)) || !object(result.question,['mission_id','objective']) || !fact(result.question.mission_id,'id') || !fact(result.question.objective,'text',true) ||
      !object(result.conclusion,['stage','statements']) || !labelValue(result.conclusion.stage) || !list(result.conclusion.statements,4096,x => object(x,['template_id','text','sources']) && tokenValue(x.template_id) && string(x.text) && list(x.sources,64,engineeringPointer)) ||
      !list(result.tasks,256,task) || !list(result.attempts,2048,attempt)) return false;
  const integration = result.integration, control = result.control, provenance = result.provenance;
  return object(integration,['stage','continuation_id','continuation_state','lead_integration_revision','evidence_id','evidence_continuation_id','recorded_verdict','payload_verdict','current','result','builds','diagnostics']) && labelValue(integration.stage) &&
    facts(integration,{continuation_id:'identity',continuation_state:'token',lead_integration_revision:'int',evidence_id:'identity',evidence_continuation_id:'identity',recorded_verdict:'token',payload_verdict:'token',current:'bool'}) &&
    (integration.result === null || artifact(integration.result)) && list(integration.builds,256,build) && diagnostics(integration.diagnostics) &&
    object(control,['phase','paused','stopped','project_verified','all_verified','reason','unresolved','live_runtime']) && facts(control,{phase:'token',paused:'bool',stopped:'bool',project_verified:'bool',all_verified:'bool',reason:'text'}) && control.live_runtime === 'NOT_PROJECTED' &&
    list(control.unresolved,2048,x => object(x,['key','associated_task_id']) && fact(x.key,'id') && (x.associated_task_id === null || (string(x.associated_task_id,256) && x.associated_task_id.length > 0))) &&
    object(provenance,['capture_basis','captured_at','event_cursor','event_head_hash','pinned','bytes_reverified','projection_is_acceptance','redaction','mission_id_source','revision','resume_epoch','selected_source_fields']) &&
    provenance.capture_basis === 'CALLER_CAPTURED_NON_ATOMIC' && provenance.captured_at === null && provenance.event_cursor === null && provenance.event_head_hash === null &&
    provenance.pinned === false && provenance.bytes_reverified === false && provenance.projection_is_acceptance === false &&
    provenance.redaction === 'UPSTREAM_CONTROLLER_REDACT_ASSUMED_PLUS_S0_PATTERN_FILTER_NOT_DLP' && provenance.mission_id_source === '/id' && facts(provenance,{revision:'int',resume_epoch:'int'}) && list(provenance.selected_source_fields,128,engineeringPointer) &&
    list(result.limitations,9,x => object(x,['code','text']) && labelValue(x.code) && string(x.text)) && diagnostics(result.diagnostics);
}
function classifyEngineering(data, id) {
  if (!Object.prototype.hasOwnProperty.call(data,'engineering_result')) return {status:'MISSING',result:null,code:null};
  const invalid = {status:'INVALID',result:null,code:'INVALID_SIDECAR'};
  try {
    const side = data.engineering_result;
    if (!engineeringObject(side,['schema','mission_id','status','result','error']) || side.schema !== 'sisyfus.lead_console.engineering_result_sidecar.v1' || side.mission_id !== id) return invalid;
    if (side.status === 'OK') return side.error === null && validEngineeringResult(side.result) ? {status:'OK',result:side.result,code:null} : invalid;
    if (!['REJECTED','FAILED'].includes(side.status) || side.result !== null || !engineeringObject(side.error,['code']) || typeof side.error.code !== 'string' || !/^[A-Z][A-Z0-9_]{0,31}$/.test(side.error.code)) return invalid;
    if (side.status === 'FAILED' && !['PROJECTION_INTERNAL_ERROR','REDACTION_ALTERED'].includes(side.error.code)) return invalid;
    return {status:side.status,result:null,code:side.error.code};
  } catch (error) { return invalid; }
}
function chatReady() {
  const chat = state.chat;
  return !!(chat && chat.proposal && typeof chat.approval_hash === 'string' && chat.approval_hash && chat.readiness?.ready === true && chat.status === 'IDLE' && !chat.mission_id);
}
function canPrepare() {
  return !!(state.kind === 'chat' && state.chat?.proposal && state.chat.readiness?.can_prepare === true &&
    !state.chat.mission_id && !state.loading && !state.busy);
}
function canChatStart() { return chatReady() && state.connected && !state.loading && !state.busy && !state.pending.has(pendingKey()); }
function canPrepareDirectory() {
  return !!(state.kind === 'chat' && state.chat?.directory_request?.status === 'READY' && !state.chat.source &&
    ['IDLE','ERROR'].includes(state.chat.status) && !state.chat.mission_id && state.connected &&
    !state.loading && !state.loadError && !state.busy && !state.pending.has(pendingKey()));
}
function canSend() {
  if (state.kind === 'mission') {
    return !state.busy && !state.loading && !state.loadError && state.connected && !!state.mission &&
      !state.pending.has(missionMessageKey(state.id));
  }
  return !state.busy && !state.loading && !state.loadError && !state.pending.has(pendingKey()) &&
    !state.pending.has('create') && state.connected && state.kind !== 'mission' &&
    (state.kind === 'welcome' || state.chat?.status === 'IDLE' || state.chat?.status === 'ERROR') &&
    !state.chat?.mission_id;
}
function renderAvailability() {
  $('composer-help').replaceChildren($('model-label'),node('span','Enter 发送 · Shift + Enter 换行'));
  $('send').disabled = !canSend() || !$('composer-input').value.trim();
  $('composer-input').readOnly = !!state.busy || !!state.chat?.mission_id || state.chat?.status === 'UNKNOWN';
  $('composer-input').placeholder = state.kind === 'mission' ? '/btw 查询进度，或输入补充资料…' : state.chat?.mission_id ? '方案已冻结；前往任务对话补充资料或查询进度。' : '你想一起做什么？';
  $('save-context').disabled = state.kind === 'mission' || !!state.busy || state.loading ||
    state.pending.has(pendingKey()) || state.pending.has('create') || !state.connected ||
    (state.chat && (state.chat.status !== 'IDLE' && state.chat.status !== 'ERROR' || !!state.chat.mission_id));
  $('attach-mission').disabled = $('save-context').disabled || !$('existing-project').value;
  $('existing-project').disabled = $('save-context').disabled;
  $('review-plan').disabled = !canPrepare();
  $('prepare-directory').disabled = !canPrepareDirectory();
  $('chat-start').disabled = !canChatStart() || !$('chat-permission').checked;
  $('chat-prepare-placement').disabled = !planningAllowed() || !$('chat-planning-permission').checked;
  $('chat-placement-retry').hidden = state.pending.get(pendingKey())?.type !== 'prepare-placement';
  $('chat-placement-retry').disabled = !planningRetryAllowed();
  $('new-chat').disabled = !!state.busy || state.pending.has('create');
  renderControlAvailability();
  renderMachineAvailability();
}
function missingContextMessage(chat) {
  if (chat.readiness?.reason) return text(chat.readiness.reason);
  if (!chat.source && !chat.spec_path) return '我们可以先把想法聊清楚。开工前，还需要选定工程目录，以及已经批准的验收文件。';
  if (!chat.source) return '方案可以继续讨论。开工前，请先告诉我这次要处理的工程目录。';
  if (!chat.spec_path) return '工程已选好。开工前，再绑定已批准的验收文件，让每项工作都有明确的判断标准。';
  if (!chat.proposal && array(chat.checks).length) return '工程与固定验收已绑定。把目标告诉我，我们先一起形成方案。';
  return chat.readiness?.ready === false ? text(chat.readiness.reason) || '开工条件还需确认。请检查工程与已批准的验收文件。' : '';
}
function renderChat() {
  const chat = state.chat; if (!chat) return;
  $('view-title').textContent = chat.title || '新的对话';
  $('view-subtitle').textContent = chat.mission_id ? '方案已关联任务 · 验收以核心记录为准' : '先聊清目标，开工由你决定';
  const area = $('scroll-area'), wasAtBottom = area.scrollHeight - area.scrollTop - area.clientHeight < 140;
  const changed = paint('messages', chat.messages, () => chat.messages.map(message => {
    const role = message.role === 'user' ? 'user' : 'assistant';
    const row = node('article', undefined, 'message ' + role);
    row.append(node('div', role === 'user' ? '你' : message.kind === 'directory' ? '工程准备' : message.kind === 'rsi' ? 'RSI 编排准备' : '技术负责人', 'message-author'), node('div', message.text || '', 'message-text prose'));
    return row;
  }));
  if (changed) { state.forceScroll = state.forceScroll || wasAtBottom; scrollLatest(); }
  const pending = state.pending.get(pendingKey());
  $('waiting').hidden = chat.status !== 'RUNNING' && !(state.busy?.type === 'message' && state.busy.id === chat.id);
  $('waiting-text').textContent = state.busy?.type === 'message' ? '正在发送这条消息…' : '正在思考，回复会出现在这里。无需重复发送。';
  let note = state.chatNotice || missingContextMessage(chat);
  if (pending) note = '这次' + ({message:'消息',start:'开工',context:'设置保存',attach:'工程复用',directory:'目录准备','prepare-placement':'子任务规划'}[pending.type] || '操作') + '的结果尚未确认。已暂停新的提交；请查询记录，系统不会自动重发。';
  else if (chat.status === 'UNKNOWN') note = '上一次调用的结果仍待确认。先查询最新记录，不重复发起调用。';
  else if (chat.status === 'ERROR') note = '这次对话遇到了问题。' + (chat.error ? ' ' + clean(typeof chat.error === 'string' ? chat.error : chat.error.message || '') : '') + ' 你可以先核对记录，再继续讨论。';
  if (chat.mission_id && !pending) note = '这段方案已绑定任务并保持冻结。前往任务对话查询进度或补充资料；讨论另一个目标请新建对话。';
  $('chat-note').hidden = !note;
  $('chat-note-text').textContent = note;
  $('context-action').hidden = !!pending || chat.status === 'UNKNOWN' || !!chat.mission_id;
  $('uncertain-refresh').hidden = !pending && chat.status !== 'UNKNOWN';
  $('uncertain-ack').hidden = !pending || !['message','context','attach'].includes(pending.type) || chat.status !== 'IDLE' || !state.connected;
  renderProposal(chat);
  const requested = chat.model?.requested, actual = chat.model?.actual;
  $('model-label').textContent = actual ? '实际模型：' + text(actual) : (requested ? '请求模型：' + text(requested) + ' · 运行待确认' : '运行模型待确认');
  $('composer-settings').textContent = chat.source ? '工程 · ' + chat.source.split('/').filter(Boolean).pop() : '＋ 设置工程与验收';
}
function listSection(title, items) {
  const result = [];
  if (!array(items).length) return result;
  result.push(node('h3', title)); const list = node('ul', undefined, 'plain-list');
  for (const item of items) list.append(node('li', text(item), 'prose'));
  result.push(list); return result;
}
function renderProposal(chat) {
  const proposal = chat.proposal;
  $('proposal').hidden = !proposal; $('proposal-actions').hidden = !proposal && !chat.mission_id;
  if (proposal) paint('proposal-body', proposal, () => {
    const allTasks = array(proposal.tasks);
    const rows = [node('h2','实施方案 · ' + allTasks.length + ' 项工作')];
    if (proposal.architecture) rows.push(node('p',previewText(proposal.architecture),'proposal-preview'));
    const preview = node('ol',undefined,'proposal-preview-tasks');
    for (const task of allTasks.slice(0,5)) {
      const item = node('li'), title = node('span',previewText(task.title || '待细化任务',60));
      title.title = task.title || '待细化任务'; item.append(title); preview.append(item);
    }
    rows.push(preview);
    if (allTasks.length > 5) rows.push(node('p','另有 ' + (allTasks.length - 5) + ' 项，见完整方案。','small muted'));
    const full = node('details',undefined,'full-proposal'); full.id = 'full-proposal'; full.dataset.detail = 'full-proposal';
    const summary = node('summary','完整方案与验收'); summary.dataset.focus = 'full-proposal-summary'; full.append(summary);
    const body = node('div',undefined,'full-proposal-body');
    body.append(node('h3','完整目标'),node('p',proposal.objective || '待明确','prose'));
    body.append(...listSection('交付什么',proposal.deliverables),...listSection('遵守的边界',proposal.constraints));
    if (proposal.architecture) body.append(node('h3','完整实现思路'),node('p',proposal.architecture,'prose'));
    if (allTasks.length) {
      body.append(node('h3','任务与逐项验收')); const tasks = node('ol',undefined,'proposal-tasks');
      for (const task of allTasks) {
        const item = node('li'); item.append(node('div',task.title || '待细化任务','task-title prose'),node('div','验收：' + (text(task.acceptance) || '待明确'),'task-acceptance prose'));
        if (array(task.depends_on).length) item.append(node('div','依赖：' + task.depends_on.map(text).join('、'),'task-acceptance prose'));
        tasks.append(item);
      }
      body.append(tasks);
    }
    body.append(node('p','这是讨论中的草案。文字验收还需落实为固定检查，经你审阅后绑定；下方检查清单会说明准备状态。','small muted'));
    full.append(body); rows.push(full); return rows;
  });
  $('review-plan').hidden = !proposal || !!chat.mission_id;
  $('linked-mission').hidden = !chat.mission_id;
  $('readiness-note').textContent = chat.mission_id ? '这段方案已关联执行任务，前往进度页查看真实状态。' :
    chatReady() ? '工程与固定验收已就绪。审阅范围、确认本地执行许可后再开工。' :
    chat.status === 'RUNNING' ? '先等这次回复，再审阅最新方案。' : missingContextMessage(chat) || '方案仍待准备，请继续讨论或检查设置。';
  const fingerprint = JSON.stringify([chat.approval_hash,chat.source,chat.spec_path,chat.checks,proposal,chat.readiness?.ready,chat.mission_id]);
  if (state.confirmFingerprint && state.confirmFingerprint !== fingerprint) {
    const hadConfirmation = !!state.confirmedApprovalHash;
    $('chat-confirm').hidden = true; $('chat-permission').checked = false; $('chat-planning-permission').checked = false; state.confirmedApprovalHash = null;
    if (hadConfirmation && !chat.mission_id) say('开工范围已变化，请重新审阅并确认。');
  }
  state.confirmFingerprint = fingerprint;
  if (!proposal || chat.mission_id) { $('preflight').hidden = true; $('review-plan').setAttribute('aria-expanded','false'); }
  else if (!$('preflight').hidden) renderPreflight(chat);
  if (!chatReady()) { $('chat-confirm').hidden = true; $('chat-permission').checked = false; $('chat-planning-permission').checked = false; state.confirmedApprovalHash = null; }
}
function renderPreflight(chat) {
  const requirements = array(chat.readiness?.requirements), missing = requirements.filter(item => item.ready !== true);
  $('preflight-summary').textContent = missing.length ? '方案已整理，还需准备 ' + missing.length + ' 项：' + missing.map(item => text(item.label)).join('、') + '。' : '前置条件已绑定。继续审阅范围并确认执行许可；尚未开工。';
  paint('preflight-requirements',requirements,() => requirements.map(item => {
    const row = node('li');
    row.append(node('strong',(item.ready === true ? '✓ 已具备 · ' : '○ 待准备 · ') + text(item.label),item.ready === true ? 'good' : ''),node('p',text(item.detail),'prose'));
    return row;
  }));
  $('preflight-note').textContent = !state.connected || state.loadError ? '当前连接未确认，清单基于上次读取记录。恢复连接并查询最新状态后再确认开工。' :
    state.pending.has(pendingKey()) ? '上次提交的结果仍待确认；先查询记录，不重复开工。' :
    '这里只检查已绑定的前置条件，不运行测试、不创建目录、不调用 Agent。正式开工时会再次核对验收脚本。';
  $('preflight-settings').hidden = !missing.some(item => item.id === 'source' || item.id === 'acceptance');
  $('prepare-directory').hidden = chat.directory_request?.status !== 'READY' || !!chat.source;
  $('acceptance-help').hidden = !missing.some(item => item.id === 'acceptance');
}
function reviewPlan() {
  if (!canPrepare()) return;
  renderPreflight(state.chat); $('preflight').hidden = false; $('review-plan').setAttribute('aria-expanded','true');
  // Inspection and preparation are read-only; only a ready, connected draft
  // may show the separate execution-permission confirmation.
  if (!canChatStart()) {
    $('chat-confirm').hidden = true; $('chat-permission').checked = false; $('chat-planning-permission').checked = false; state.confirmedApprovalHash = null;
    renderAvailability(); $('preflight').scrollIntoView({block:'nearest'}); $('preflight-title').focus({preventScroll:true}); return;
  }
  confirmationContext($('chat-confirm-context'),state.chat.source,state.chat.spec_path,checksForChat(state.chat).map(check => check.id || check.check).filter(Boolean));
  const rsi = state.chat.rsi_configuration;
  if (rsi) $('chat-confirm-context').append(node('dt','RSI'),node('dd',rsi.enabled === false ? '已关闭' :
    (rsi.evaluation_root ? '固定评估集：' + rsi.evaluation_root : '未绑定评估集；仅保留策略提议') + ' · ' + (rsi.auto_promote === false ? '只评估，不自动晋升' : '通过全部门槛后自动晋升')));
  state.confirmedApprovalHash = state.chat.approval_hash;
  $('chat-confirm').hidden = false; $('chat-permission').checked = false; $('chat-planning-permission').checked = false; renderAvailability(); $('chat-permission').focus();
}
function checksForChat(chat) { return array(chat?.checks); }
function checkNamesForMission() {
  const snapshot = state.mission?.snapshot || {};
  const names = array(snapshot.nodes).map(task => task.check).filter(Boolean);
  for (const check of verificationChecks(snapshot.integration?.evidence?.payload)) if (check.check) names.push(check.check);
  return [...new Set(names)];
}
function confirmationContext(root, source, spec, checks) {
  const rows = [['工程', source || '尚未绑定'], ['验收文件', spec || '已绑定任务的固定验收'], ['验收项目', checks.length ? checks.join('、') : '项目名称暂未读到，请先核对验收设置']];
  root.replaceChildren(...rows.flatMap(([name,value]) => [node('dt',name), node('dd',value)]));
}
async function createChat() {
  const data = validateChat(await api('/api/chats', {}), null, true); upsertChat(data); clearPending('create'); return data;
}
async function newChat() {
  if (state.busy || state.pending.has('create')) return;
  const epoch = state.epoch; state.busy = {type:'create'}; renderAvailability();
  try {
    const chat = await createChat();
    if (state.epoch === epoch) { switchView('chat',chat.id); state.loading = false; networkSuccess(); applyChat(chat); $('composer-input').focus(); }
    renderLists();
  } catch (error) {
    if (error.uncertain) setPending('create',{type:'create',at:Date.now()});
    showGlobal(error.uncertain ? '新对话的创建结果待确认。请先查询侧栏记录；不会自动创建第二次。' : clean(error.message), error.uncertain);
    await inventory();
  } finally { state.busy = null; renderAvailability(); }
}
function markUncertain(key, operation, error) {
  if (error.uncertain) setPending(key,{...operation,at:Date.now()});
}
function missionMessageKey(id) { return 'mission-message:' + id; }
const missionInboxCacheSchema = 2;
function missionInbox(id) {
  if (!state.inboxes.has(id)) {
    const inbox = {messages:[],localReceipts:[],wireMode:null,cursor:0,application_cursor:0,has_more:true,has_more_updates:true,
      loaded:false,reading:false,readSerial:0,renderVersion:0,error:'',notice:'',cacheIssue:'',retryRequest:null};
    try {
      const saved = JSON.parse(sessionStorage.getItem(storageKey + ':inbox:' + encodeURIComponent(id)) || 'null');
      if (saved) {
        const wireMode = saved.wire_mode ?? (saved.loaded === true ||
          (Number.isSafeInteger(saved.application_cursor) && saved.application_cursor > 0) ? 'canonical' : null);
        // Protocol identity survives cache invalidation; an upgrade is never a canonical downgrade.
        if (saved.mission_id === id && [null,'canonical','legacy'].includes(wireMode)) inbox.wireMode = wireMode;
        if (saved.schema === 1 && saved.mission_id === id && [null,'canonical','legacy'].includes(wireMode)) {
          // Old BOUND projections may have passed a terminal call with no update event.
          // Invalidate that projection and replay both streams from zero in bounded rounds.
          inbox.cacheIssue = '任务消息缓存版本已升级，将从零重读消息与应用状态；旧投影不作为最新记录，后续轮次继续追赶。';
        } else {
          if (saved.schema !== missionInboxCacheSchema || saved.mission_id !== id || !Array.isArray(saved.messages) ||
              !Number.isSafeInteger(saved.cursor) || saved.cursor < 0 ||
              !Number.isSafeInteger(saved.application_cursor) || saved.application_cursor < 0 ||
              typeof saved.loaded !== 'boolean' || typeof saved.has_more !== 'boolean' || typeof saved.has_more_updates !== 'boolean' ||
              (saved.wire_mode !== undefined && ![null,'canonical','legacy'].includes(saved.wire_mode)) ||
              (saved.local_receipts !== undefined && !Array.isArray(saved.local_receipts))) {
            throw new RequestError('任务消息缓存格式不完整。');
          }
          const messages = mergeMissionMessages([],saved.messages.map(item => validateMissionMessage(item)));
          if (messages.length !== saved.messages.length || (saved.cursor > 0 && !messages.some(item => item.seq === saved.cursor))) {
            throw new RequestError('任务消息缓存缺少游标对应的历史记录。');
          }
          const localReceipts = mergeMissionMessages([],array(saved.local_receipts).map(item => validateMissionMessage(item)));
          if (mergeMissionMessages(messages,localReceipts).length !== messages.length) throw new RequestError('任务消息缓存缺少已确认的提交回执。');
          Object.assign(inbox,{messages,cursor:saved.cursor,application_cursor:saved.application_cursor,
            localReceipts,wireMode,loaded:saved.loaded,has_more:saved.has_more,has_more_updates:saved.has_more_updates});
        }
      }
    } catch (error) {
      inbox.cacheIssue = '任务消息缓存读取失败，将从历史起点重新追赶：' + clean(error.message);
    }
    state.inboxes.set(id,inbox);
  }
  return state.inboxes.get(id);
}
function persistMissionInbox(id, inbox) {
  try {
    // Store records and their read boundary atomically; cursor-only cache loses history on refresh.
    sessionStorage.setItem(storageKey + ':inbox:' + encodeURIComponent(id),JSON.stringify({schema:missionInboxCacheSchema,mission_id:id,
      messages:inbox.messages,local_receipts:inbox.localReceipts,wire_mode:inbox.wireMode,
      cursor:inbox.cursor,application_cursor:inbox.application_cursor,
      loaded:inbox.loaded,has_more:inbox.has_more,has_more_updates:inbox.has_more_updates}));
    inbox.cacheIssue = '';
  } catch (error) {
    inbox.cacheIssue = '消息缓存存储失败；新读回记录仍保存在本页。刷新后从上次成功保存的边界继续追赶，不跳过历史。';
  }
}
function validateMissionMessage(message, uncertain = false) {
  if (!message || typeof message.id !== 'string' || !message.id ||
      !Number.isSafeInteger(message.seq) || message.seq < 1 ||
      typeof message.request_id !== 'string' || !message.request_id || typeof message.text !== 'string' ||
      !['query','context'].includes(message.kind) || !['RECEIVED','APPLIED','ANSWERED'].includes(message.status) ||
      !Array.isArray(message.applications) || message.applications.some(item => !item ||
        typeof item.run_key !== 'string' || !item.run_key || typeof item.role !== 'string' ||
        !['BOUND','APPLIED','NOT_APPLIED'].includes(item.status)) ||
      (message.kind === 'query' && (!message.answer || typeof message.answer.summary !== 'string' ||
        typeof message.answer.phase !== 'string' || !Array.isArray(message.answer.blockers) ||
        !Array.isArray(message.answer.latest_results) || !Array.isArray(message.answer.active_tasks)))) {
    throw new RequestError('任务消息记录格式不完整，请查询原请求回执。',uncertain);
  }
  return message;
}
function mergeMissionMessages(previous, incoming, uncertain = false) {
  const rows = new Map(previous.map(message => [message.id,message]));
  const requests = new Map(previous.map(message => [message.request_id,message.id]));
  const sequences = new Map(previous.map(message => [message.seq,message.id]));
  for (const message of incoming) {
    const known = rows.get(message.id);
    if ((known && ['seq','request_id','kind','text'].some(key => known[key] !== message[key])) ||
        (requests.has(message.request_id) && requests.get(message.request_id) !== message.id) ||
        (sequences.has(message.seq) && sequences.get(message.seq) !== message.id)) {
      throw new RequestError('任务消息历史身份异常，请核对原请求回执。',uncertain);
    }
    // Reuse unchanged records so an idle poll or an unrelated update does not rebuild every row.
    if (!known || JSON.stringify(known) !== JSON.stringify(message)) rows.set(message.id,message);
    requests.set(message.request_id,message.id); sequences.set(message.seq,message.id);
  }
  return [...rows.values()].sort((a,b) => a.seq - b.seq);
}
function applyMissionMessages(inbox, messages, uncertain = false) {
  const merged = mergeMissionMessages(inbox.messages,messages,uncertain);
  if (merged.length === inbox.messages.length && merged.every((message,index) => message === inbox.messages[index])) return false;
  inbox.messages = merged; inbox.renderVersion++; return true;
}
function reconcileMissionMessages(id, messages) {
  const key = missionMessageKey(id), pending = state.pending.get(key);
  // Never use the next arbitrary user message, a status answer or a control ACK.
  if (pending?.type === 'mission-message' && messages.some(message => message.request_id === pending.request_id)) clearPending(key);
}
function hasApplicationStream(batch) {
  return ['updates','application_cursor','has_more_updates'].some(key => key in batch);
}
async function readLegacyMissionSnapshot(id, firstBatch, firstCursor, ownsRead, deadline) {
  // Legacy has no monotonic update channel: stage one bounded full read, never partial projection.
  let batch = firstCursor === 0 ? firstBatch : null, cursor = 0;
  const rows = [], ids = new Set(), requests = new Set();
  for (let page = 0; page < 40; page++) {
    if (!ownsRead()) return null;
    const remaining = deadline - Date.now();
    if (remaining <= 0) throw new RequestError('旧协议完整历史读取达到时间上限，请重新查询。');
    if (!batch) batch = await api('/api/mission/messages?mission_id=' + encodeURIComponent(id) + '&cursor=' + cursor,
      undefined,Math.min(14000,remaining));
    if (!ownsRead()) return null;
    if (!batch || hasApplicationStream(batch) || !Array.isArray(batch.messages) ||
        !Number.isSafeInteger(batch.cursor) || batch.cursor < cursor || typeof batch.has_more !== 'boolean' ||
        (!batch.messages.length && batch.cursor !== cursor) ||
        (batch.has_more && (!batch.messages.length || batch.cursor <= cursor))) {
      throw new RequestError('旧协议完整历史响应或游标异常，请重新查询。');
    }
    let lastSeq = cursor;
    for (const item of batch.messages) {
      const message = validateMissionMessage(item);
      if (message.seq <= lastSeq || message.seq > batch.cursor || ids.has(message.id) || requests.has(message.request_id)) {
        throw new RequestError('旧协议完整历史编号异常，请重新查询。');
      }
      ids.add(message.id); requests.add(message.request_id); rows.push(message); lastSeq = message.seq;
    }
    if (lastSeq !== batch.cursor) throw new RequestError('旧协议完整历史末尾游标异常，请重新查询。');
    if (rows.length > 10000) throw new RequestError('旧协议完整历史达到记录上限，请核对诊断。');
    cursor = batch.cursor;
    if (!batch.has_more) return {messages:rows,cursor};
    batch = null;
  }
  throw new RequestError('旧协议完整历史达到分页上限（40 页）；保留上次投影，请核对诊断。');
}
function replaceLegacyMissionProjection(inbox, messages) {
  // Only a completed fieldless snapshot may replace its previous projection's identities.
  // A received POST is independent positive evidence if this GET predates its persistence.
  const requests = new Set(messages.map(message => message.request_id));
  const receipts = inbox.localReceipts.filter(message => !requests.has(message.request_id));
  const projection = mergeMissionMessages([], [...messages,...receipts]);
  const previous = new Map(inbox.messages.map(message => [message.id,message]));
  const merged = projection.map(message => {
    const known = previous.get(message.id);
    return known && JSON.stringify(known) === JSON.stringify(message) ? known : message;
  });
  if (merged.length !== inbox.messages.length || merged.some((message,index) => message !== inbox.messages[index])) inbox.renderVersion++;
  inbox.messages = merged; inbox.localReceipts = receipts;
}
async function readMissionInbox(id, current) {
  const inbox = missionInbox(id), deadline = Date.now() + 20000;
  const serial = ++inbox.readSerial, ownsRead = () => current() && inbox.readSerial === serial;
  let dirty = false;
  inbox.reading = true; inbox.retryRequest = null;
  if (current()) renderMissionInbox();
  try {
    // Bound work per round, not total history. Poll/manual refresh resumes both streams.
    for (let page = 0; page < 5; page++) {
      if (!ownsRead()) return;
      const remaining = deadline - Date.now();
      if (remaining <= 0) break;
      const cursor = inbox.wireMode === 'legacy' ? 0 : inbox.cursor, applicationCursor = inbox.application_cursor;
      const batch = await api('/api/mission/messages?mission_id=' + encodeURIComponent(id) +
        (inbox.wireMode === 'legacy' ? '' : '&application_cursor=' + applicationCursor) + '&cursor=' + cursor,
        undefined,Math.min(14000,remaining));
      if (!ownsRead()) return;
      if (!batch || !Array.isArray(batch.messages) || !Number.isSafeInteger(batch.cursor) ||
          batch.cursor < cursor || typeof batch.has_more !== 'boolean' ||
          (!batch.messages.length && batch.cursor !== cursor) ||
          (batch.has_more && (!batch.messages.length || batch.cursor <= cursor))) {
        throw new RequestError('任务消息历史游标异常；保留已读边界，请重新查询。');
      }
      const extended = hasApplicationStream(batch);
      if (!extended) {
        // Once observed (or restored), canonical mode is pinned: missing fields are a protocol error, not a downgrade.
        if (inbox.wireMode === 'canonical') throw new RequestError('任务消息双游标响应缺少增量字段；未切换旧协议。');
        if (inbox.wireMode !== 'legacy') { inbox.wireMode = 'legacy'; dirty = true; }
        const snapshot = await readLegacyMissionSnapshot(id,batch,cursor,ownsRead,deadline);
        if (!ownsRead() || !snapshot) return;
        replaceLegacyMissionProjection(inbox,snapshot.messages);
        inbox.cursor = snapshot.cursor; inbox.application_cursor = 0;
        inbox.has_more = false; inbox.has_more_updates = false; inbox.loaded = true; inbox.error = '';
        inbox.updateIssue = '旧协议兼容：每次完整分页读取后替换历史；读取失败时保留上次投影。'; dirty = true;
        const beforePending = state.pending.get(missionMessageKey(id));
        reconcileMissionMessages(id,snapshot.messages);
        if (beforePending && !state.pending.has(missionMessageKey(id))) inbox.notice = '已按原请求编号核对收到的消息；未重新提交。';
        break;
      }
      // Any increment field identifies canonical wire, even if the rest of this response is malformed.
      if (inbox.wireMode !== 'canonical') { inbox.wireMode = 'canonical'; dirty = true; }
      const updates = batch.updates, nextApplicationCursor = batch.application_cursor, moreUpdates = batch.has_more_updates;
      if (!Array.isArray(updates) || !Number.isSafeInteger(nextApplicationCursor) || nextApplicationCursor < applicationCursor ||
          typeof moreUpdates !== 'boolean' || ((moreUpdates || updates.length) && nextApplicationCursor <= applicationCursor)) {
        throw new RequestError('任务消息应用更新游标异常；保留已读边界，请重新查询。');
      }
      const rows = [], ids = new Set(), requests = new Set(); let lastSeq = cursor;
      for (const item of batch.messages) {
        const message = validateMissionMessage(item);
        if (message.seq <= lastSeq || message.seq > batch.cursor || ids.has(message.id) || requests.has(message.request_id)) {
          throw new RequestError('任务消息历史编号异常；保留已读边界，请重新查询。');
        }
        ids.add(message.id); requests.add(message.request_id); rows.push(message); lastSeq = message.seq;
      }
      if (lastSeq !== batch.cursor) throw new RequestError('任务消息历史末尾游标异常，请重新查询。');
      const known = new Map(inbox.messages.map(message => [message.id,message]));
      for (const item of updates) {
        const message = validateMissionMessage(item);
        if (message.seq > cursor || !known.has(message.id) || ids.has(message.id) || requests.has(message.request_id)) {
          throw new RequestError('任务消息应用更新的历史身份异常，请重新查询。');
        }
        ids.add(message.id); requests.add(message.request_id); rows.push(message);
      }
      // Validate the whole response before advancing either boundary; earlier valid pages stay committed.
      const changed = applyMissionMessages(inbox,rows);
      const received = new Set(rows.map(message => message.request_id));
      const receipts = inbox.localReceipts.filter(message => !received.has(message.request_id));
      if (receipts.length !== inbox.localReceipts.length) { inbox.localReceipts = receipts; dirty = true; }
      dirty = dirty || changed || !inbox.loaded || inbox.cursor !== batch.cursor || inbox.application_cursor !== nextApplicationCursor ||
        inbox.has_more !== batch.has_more || inbox.has_more_updates !== moreUpdates;
      inbox.cursor = batch.cursor; inbox.application_cursor = nextApplicationCursor;
      inbox.has_more = batch.has_more; inbox.has_more_updates = moreUpdates; inbox.loaded = true;
      inbox.error = '';
      inbox.updateIssue = '';
      const beforePending = state.pending.get(missionMessageKey(id));
      reconcileMissionMessages(id,inbox.messages);
      if (beforePending && !state.pending.has(missionMessageKey(id))) inbox.notice = '已按原请求编号核对收到的消息；未重新提交。';
      if (!inbox.has_more && !inbox.has_more_updates) break;
    }
    if (!ownsRead()) return;
    const pending = state.pending.get(missionMessageKey(id));
    // Positive exact evidence clears at any page; absence permits explicit retry only after full catch-up.
    inbox.retryRequest = !inbox.error && !inbox.has_more && !inbox.has_more_updates && pending?.type === 'mission-message' ? pending.request_id : null;
  } catch (error) {
    if (!ownsRead()) return;
    inbox.error = (inbox.wireMode === 'legacy' ? '旧协议完整历史读取失败：' : '任务消息增量读取失败：') + clean(error.message) +
      (inbox.wireMode === 'legacy' ? ' 已保留上次投影；完整历史尚未确认。' : ' 已保留已读记录和游标，当前增量尚未核对；恢复后继续追赶。');
    inbox.retryRequest = null;
  } finally {
    if (inbox.readSerial === serial) inbox.reading = false;
    if (dirty) persistMissionInbox(id,inbox);
    if (current()) { renderMissionInbox(); renderAvailability(); }
  }
}
function queryMissionPhase(answer) {
  // Query snapshots describe the mission, not the COMPLETED receipt of one native run.
  if (answer.phase === 'COMPLETED') return answer.all_verified === true ? '任务已完成' : '执行流程已结束，整项验收尚未确认';
  return label(answer.phase);
}
function queryTaskLine(result) {
  if (typeof result === 'string') return result;
  if (!result || typeof result !== 'object') return '结果记录待核对';
  return (result.kind === 'integration' ? '集成' : text(result.objective || result.title || result.task_id || result.id) || '子任务') +
    (result.state || result.status ? ' · ' + label(result.state || result.status) : '') +
    (result.verdict ? ' · ' + label(result.verdict) : '') + (result.stale ? ' · 证据已过期' : '') +
    (result.summary ? '：' + text(result.summary) : '') + (result.evidence_id ? ' · 证据 ' + text(result.evidence_id) : '');
}
const missionMessageRows = {id:'',items:new Map()};
function renderMissionInbox() {
  if (state.kind !== 'mission') return;
  const inbox = missionInbox(state.id), pending = state.pending.get(missionMessageKey(state.id));
  const area = $('scroll-area'), atBottom = area.scrollHeight - area.scrollTop - area.clientHeight < 140;
  const changed = paint('mission-message-thread',[state.id,inbox.loaded,inbox.renderVersion],() => {
    if (missionMessageRows.id !== state.id) { missionMessageRows.id = state.id; missionMessageRows.items.clear(); }
    const visible = new Set(inbox.messages.map(message => message.id));
    for (const id of missionMessageRows.items.keys()) if (!visible.has(id)) missionMessageRows.items.delete(id);
    if (!inbox.messages.length) return [node('p',inbox.loaded ? '还没有任务消息。可以用 /btw 查询进度，或补充资料。' : '正在读取任务消息历史…','small muted')];
    return inbox.messages.map(message => {
      const previous = missionMessageRows.items.get(message.id);
      if (previous?.message === message) return previous.row;
      const row = node('article',undefined,'message');
      row.append(node('div','你 · ' + (message.kind === 'query' ? '状态查询' : '补充资料'),'message-author'),
        node('div',clean(message.text),'message-text prose'),
        node('p','已收到 · 消息 ' + clean(message.id) + ' · 请求 ' + clean(message.request_id),'small muted prose'));
      if (message.kind === 'query') {
        const answer = message.answer;
        row.append(node('div',clean(answer.summary),'message-text prose'),
          node('p','查询时阶段：' + queryMissionPhase(answer) + ' · ' + (answer.all_verified === true ? '查询快照显示验收通过' : '查询快照尚未确认整项验收'),'small muted prose'));
        if (answer.blockers.length) {
          row.append(node('h4','当前卡点','small'));
          for (const blocker of answer.blockers) row.append(node('p',clean(typeof blocker === 'string' ? blocker : queryTaskLine(blocker)),'small prose'));
        }
        if (answer.active_tasks.length) row.append(node('p','活动子任务：' + answer.active_tasks.map(queryTaskLine).map(clean).join('；'),'small prose'));
        if (answer.latest_results.length) {
          row.append(node('h4','最近结果','small'));
          for (const result of answer.latest_results) row.append(node('p',clean(queryTaskLine(result)),'small prose'));
        }
        row.append(node('p','状态快照 · 版本 ' + text(answer.revision ?? '未知') + ' · 事件游标 ' + text(answer.observed_event_cursor ?? '未知') +
          ' · ' + clean(text(answer.observed_at)) + '。这是查询时的状态，不是当前验收结论。','small muted prose'));
      } else {
        if (!message.applications.length) row.append(node('p','已收到，等待后续符合条件的调用；当前运行中的调用不会补写提示词。资料窗口有长度上限，较新的补充优先；未绑定的资料仍只表示已收到。','small muted prose'));
        for (const application of message.applications) {
          const status = application.status === 'APPLIED' ? '已应用到原生调用 · 纳入已接受调用的提示词' :
            application.status === 'NOT_APPLIED' ? '调用已结束，未记录资料被接受' : '已绑定新调用，资料交付待核对';
          row.append(node('p',status +
            ' · ' + clean(application.role) + ' · ' + clean(application.run_key) +
            (application.task_id ? ' · 子任务 ' + clean(application.task_id) : ' · 任务整体'),'small prose'));
          if (application.delivery) {
            // Delivery is diagnostic metadata, never task verification or authority.
            const receipt = node('details',undefined,'small muted'); receipt.dataset.detail = message.id + ':' + application.run_key;
            receipt.append(node('summary','查看应用回执'),node('pre',clean(application.delivery),'prose')); row.append(receipt);
          }
        }
        row.append(node('p','原生应用仅表示资料已纳入该调用提示词，不代表模型遵循、执行成功或验收通过。','small muted prose'));
      }
      if (previous) { previous.row.replaceChildren(...row.children); previous.message = message; return previous.row; }
      missionMessageRows.items.set(message.id,{message,row}); return row;
    });
  });
  const notes = [inbox.error,inbox.notice,inbox.cacheIssue,inbox.updateIssue,storageIssue];
  if (inbox.wireMode !== 'legacy' && (inbox.has_more || inbox.has_more_updates)) notes.push('已加载 ' + inbox.messages.length + ' 条历史；仍有消息或应用更新，后续轮次继续追赶。消息游标 ' + inbox.cursor + ' · 应用游标 ' + inbox.application_cursor + '。');
  if (pending) notes.push('这条消息的提交结果待确认（请求 ' + clean(pending.request_id) + '）。只按原编号查询回执，不自动重发；新消息提交已暂停。');
  if (inbox.reading) notes.push('正在按已读边界查询新消息与旧消息应用更新…');
  $('mission-inbox-note').textContent = notes.filter(Boolean).join('\n');
  $('mission-inbox-note').classList.toggle('error',!!inbox.error);
  $('mission-inbox-retry').hidden = !pending || inbox.retryRequest !== pending.request_id || !!inbox.error;
  $('mission-inbox-retry').disabled = !!state.busy || !state.connected || inbox.reading;
  $('mission-inbox-refresh').disabled = !!state.busy;
  $('model-label').textContent = '/btw 查询状态 · 普通文字补充资料 · 不启动工作';
  $('composer-settings').textContent = '查看任务工程与固定验收';
  if (changed) { state.forceScroll = state.forceScroll || atBottom; scrollLatest(); }
}
async function sendMissionMessage(retry = false) {
  const id = state.id, key = missionMessageKey(id), inbox = missionInbox(id);
  let operation;
  if (retry) {
    operation = state.pending.get(key);
    if (state.kind !== 'mission' || !operation || inbox.retryRequest !== operation.request_id ||
        inbox.error || inbox.reading || state.busy || !state.connected) return;
  } else {
    if (!canSend() || state.composing) return;
    const message = $('composer-input').value.trim(); if (!message) return;
    let uuid;
    try { uuid = requestId(); } catch (error) { inbox.notice = clean(error.message); renderMissionInbox(); return; }
    operation = {type:'mission-message',request_id:uuid,body:{mission_id:id,message,request_id:uuid},at:Date.now()};
    // Persist before transport. Refresh/interruption never creates a new identity.
    setPending(key,operation);
    $('composer-input').value = ''; state.drafts.set(draftKey(),''); resizeComposer();
  }
  if (!operation.body || operation.body.mission_id !== id || operation.body.request_id !== operation.request_id) {
    inbox.error = '待确认请求记录不完整，请核对历史与诊断；未重新提交。'; renderMissionInbox(); return;
  }
  const busy = {type:'mission-message',id}, epoch = state.epoch, version = ++state.version;
  const current = () => state.kind === 'mission' && state.id === id && state.epoch === epoch && state.version === version;
  state.busy = busy; inbox.notice = ''; inbox.retryRequest = null; render();
  try {
    const message = validateMissionMessage(await api('/api/mission/message',operation.body),true);
    // The server owns the idempotency fingerprint; returned prose is normalized/redacted display data.
    if (message.request_id !== operation.request_id) {
      throw new RequestError('提交回执与原请求不匹配，请按原编号查询。',true);
    }
    if (current()) {
      const receipts = mergeMissionMessages(inbox.localReceipts,[message],true);
      applyMissionMessages(inbox,[message],true); inbox.localReceipts = receipts;
      persistMissionInbox(id,inbox);
      renderMissionInbox();
    }
    reconcileMissionMessages(id,[message]);
  } catch (error) {
    if (!error.uncertain) {
      clearPending(key);
      if (!retry) state.drafts.set(draftKey('mission',id),operation.body.message);
      if (current() && !retry && !$('composer-input').value) { $('composer-input').value = operation.body.message; resizeComposer(); }
    }
    if (current()) inbox.notice = clean(error.message) + (error.uncertain ? ' 提交结果待确认，正在查询原请求回执。' : ' 请求被拒绝，未自动重发。');
  } finally {
    if (state.busy === busy) state.busy = null;
    if (current()) {
      state.version++; render();
      const readVersion = state.version;
      await readMissionInbox(id,() => state.kind === 'mission' && state.id === id && state.epoch === epoch && state.version === readVersion);
      renderAvailability();
    } else renderAvailability();
  }
}
async function sendMessage() {
  if (state.composing) return;
  if (state.kind === 'mission') return sendMissionMessage();
  if (!canSend()) return;
  const message = $('composer-input').value.trim(); if (!message) return;
  const epoch = state.epoch; let id = state.chat?.id, sent = false, uuid;
  try { uuid = requestId(); } catch (error) { showGlobal(error.message); return; }
  state.busy = {type:'message',id}; state.version++; renderAvailability();
  try {
    if (!id) {
      let created;
      try { created = await createChat(); }
      catch (error) {
        markUncertain('create',{type:'create'},error);
        showGlobal(error.uncertain ? '对话创建结果待确认，消息尚未发送。请先核对列表。' : clean(error.message),error.uncertain);
        await inventory(); return;
      }
      id = created.id; state.busy.id = id;
      if (state.epoch !== epoch) { showGlobal('新对话已建立，消息尚未发送。可以从侧栏打开后继续。'); renderLists(); return; }
      state.drafts.set(draftKey('chat',id),message); switchView('chat',id); state.loading = false; applyChat(created);
    }
    const ownerEpoch = state.epoch;
    const before = array(state.chat?.messages).map(item => item.id).filter(Boolean);
    $('composer-input').value = ''; state.drafts.set(draftKey('chat',id),''); resizeComposer(); state.forceScroll = true;
    state.chatNotice = ''; render(); sent = true;
    try {
      const chat = validateChat(await api('/api/chat/message',{chat_id:id,message,request_id:uuid}),id,true);
      upsertChat(chat);
      if (state.kind === 'chat' && state.id === id && state.epoch === ownerEpoch) applyChat(chat);
    } catch (error) {
      markUncertain('chat:' + id,{type:'message',request_id:uuid,before},error);
      if (!error.uncertain) {
        state.drafts.set(draftKey('chat',id),message);
        if (state.kind === 'chat' && state.id === id && !$('composer-input').value) { $('composer-input').value = message; resizeComposer(); }
      }
      if (state.kind === 'chat' && state.id === id) state.chatNotice = clean(error.message);
      else showGlobal(error.uncertain ? '一条消息的结果待确认，请回到原对话核对记录。' : clean(error.message));
    }
  } finally {
    state.busy = null; state.version++; render();
    if (sent && state.kind === 'chat' && state.id === id) await readSelected();
    renderLists();
  }
}
async function startChat(event) {
  event.preventDefault();
  if (!canChatStart() || !$('chat-permission').checked || $('chat-confirm').hidden) return;
  const id = state.id, epoch = state.epoch, approval_hash = state.confirmedApprovalHash; let uuid;
  if (!approval_hash || approval_hash !== state.chat.approval_hash) {
    $('chat-confirm').hidden = true; $('chat-permission').checked = false; state.confirmedApprovalHash = null;
    state.chatNotice = '方案已更新，请重新审阅范围后确认开工。'; render(); return;
  }
  try { uuid = requestId(); } catch (error) { state.chatNotice = error.message; render(); return; }
  state.busy = {type:'start',id}; state.version++; renderAvailability();
  try {
    const chat = validateChat(await api('/api/chat/start',{chat_id:id,allow_local_workers:true,request_id:uuid,approval_hash}),id,true);
    upsertChat(chat); clearPending('chat:' + id);
    if (state.epoch === epoch && state.id === id) {
      applyChat(chat); $('chat-confirm').hidden = true; $('chat-permission').checked = false; state.confirmedApprovalHash = null;
      if (chat.mission_id) await selectMission(chat.mission_id);
      else state.chatNotice = '开工请求已接收，等待任务编号。先查询状态，不重复开工。';
    }
    if (!chat.mission_id) setPending('chat:' + id,{type:'start',request_id:uuid,at:Date.now()});
  } catch (error) {
    markUncertain('chat:' + id,{type:'start',request_id:uuid},error);
    if (state.epoch === epoch) { state.chatNotice = clean(error.message); $('chat-permission').checked = false; state.confirmedApprovalHash = null; $('chat-confirm').hidden = true; }
    else showGlobal(error.uncertain ? '开工结果待确认，请回到原对话查询。' : clean(error.message));
  } finally {
    state.busy = null; state.version++; render();
    if (state.kind === 'chat' && state.id === id) await readSelected();
    await inventory();
  }
}
function planningAllowed() {
  return state.kind === 'chat' && canChatStart() && !state.loadError && !$('chat-confirm').hidden &&
    !!state.confirmedApprovalHash && state.confirmedApprovalHash === state.chat.approval_hash;
}
function planningRetryAllowed() {
  const pending = state.pending.get(pendingKey());
  return !!(state.kind === 'chat' && pending?.type === 'prepare-placement' && pending.body &&
    pending.body.chat_id === state.id && pending.body.request_id === pending.request_id &&
    pending.body.allow_planning === true && pending.body.approval_hash === state.chat?.approval_hash &&
    pending.source === state.chat?.source && pending.spec_path === state.chat?.spec_path &&
    chatReady() && state.connected && !state.loading && !state.loadError && !state.busy);
}
function matchingPreparation(chat,operation) {
  const proof = chat.placement_preparation;
  return !!(planningAcknowledged(chat) &&
    proof.request_id === operation.request_id && proof.approval_hash === operation.body?.approval_hash);
}
function planningAcknowledged(chat) {
  const proof = chat?.placement_preparation;
  if (!(chat?.mission_id && /^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$/.test(chat.mission_id) &&
    proof && proof.mission_id === chat.mission_id && proof.scope === 'planning_only' &&
    proof.status === 'ACK' && typeof proof.request_id === 'string' && proof.request_id &&
    /^[a-f0-9]{64}$/.test(proof.approval_hash || '') && /^[a-f0-9]{64}$/.test(proof.spec_hash || ''))) return false;
  const expected = {id:'prepare-placement:' + proof.request_id,mission_id:chat.mission_id,request_id:proof.request_id,
    action:'prepare-placement',status:'ACK',accepted:true,terminal:false,scope:'planning_only'};
  const control = proof.control;
  return !!(control && typeof control === 'object' && !Array.isArray(control) &&
    Object.keys(control).length === Object.keys(expected).length &&
    Object.entries(expected).every(([key,value]) => control[key] === value));
}
async function preparePlacement(retry = false) {
  if (retry ? !planningRetryAllowed() : !planningAllowed() || !$('chat-planning-permission').checked) return;
  const id = state.id, epoch = state.epoch, key = 'chat:' + id;
  let operation = retry ? state.pending.get(key) : null;
  if (!operation) {
    let uuid;
    try { uuid = requestId(); } catch (error) { state.chatNotice = clean(error.message); render(); return; }
    operation = {type:'prepare-placement',request_id:uuid,source:state.chat.source,spec_path:state.chat.spec_path,
      body:{chat_id:id,allow_planning:true,request_id:uuid,approval_hash:state.confirmedApprovalHash},at:Date.now()};
    setPending(key,operation);
  }
  const busy = {type:'prepare-placement',id}; state.busy = busy; state.version++; renderAvailability();
  try {
    const chat = validateChat(await api('/api/chat/prepare-placement',operation.body),id,true);
    upsertChat(chat);
    if (!matchingPreparation(chat,operation)) throw new RequestError('规划受理记录尚未核对到原请求，请查询记录。',true);
    clearPending(key);
    if (state.kind === 'chat' && state.id === id && state.epoch === epoch) {
      applyChat(chat); $('chat-planning-permission').checked = false;
      state.chatNotice = '仅规划请求已受理；进入原任务查询准备与机器选择，尚未启动 Sol。';
      await selectMission(chat.mission_id);
    }
  } catch (error) {
    if (!error.uncertain) clearPending(key);
    if (state.kind === 'chat' && state.id === id && state.epoch === epoch) {
      state.chatNotice = clean(error.message); $('chat-planning-permission').checked = false;
    }
  } finally {
    if (state.busy === busy) state.busy = null;
    // A late result belongs to its original chat; do not invalidate an
    // in-progress read belonging to the newly selected mission.
    if (state.kind === 'chat' && state.id === id && state.epoch === epoch) state.version++;
    render();
    if (state.kind === 'chat' && state.id === id && state.epoch === epoch) await readSelected();
  }
}
function machineKey(id) { return 'machine:' + id; }
function machineView(id) {
  if (!state.machines.has(id)) state.machines.set(id,{loaded:false,nodes:[],placements:[],error:'',notice:'',serial:0,fresh:null,exportNode:''});
  return state.machines.get(id);
}
function validMachineName(name) {
  try { return typeof name === 'string' && !!name && name === name.trim() && !/[\x00-\x1f\x7f]/.test(name) &&
    encodeURIComponent(name).replace(/%[a-f0-9]{2}|./gi,'x').length <= 200 &&
    !(token && name.includes(token)) && !/[a-f0-9]{64}/i.test(name); } catch (error) { return false; }
}
function machineIntentPath(id,operation) {
  // Persisted browser data grants no new route, payload field or identity.
  // eee stored no path/mission_id: derive only its original fixed public route.
  const body = operation?.body, keys = body && typeof body === 'object' && !Array.isArray(body) ? Object.keys(body) : [];
  if (!body || typeof body !== 'object' || Array.isArray(body) || !/^m_[a-f0-9]{32}$/.test(id) ||
      (operation.mission_id !== undefined && operation.mission_id !== id)) return null;
  const bounded = value => typeof value === 'string' && !!value && value.length <= 200 &&
    !/[\x00-\x1f\x7f]/.test(value) && !(token && value.includes(token)) &&
    ![...nodeSecretRedactions].some(secret => value.includes(secret));
  const sameRequest = bounded(operation.request_id) && body.request_id === operation.request_id;
  let suffix;
  if (operation.type === 'placement' && keys.length === 3 &&
      keys.every(key => ['request_id','task_id','node_id'].includes(key)) && sameRequest &&
      bounded(body.task_id) && /^node_[a-f0-9]{32}$/.test(body.node_id || '')) suffix = '/placements';
  else if (operation.type === 'node-enroll' && keys.length === 2 &&
      keys.every(key => ['request_id','name'].includes(key)) && sameRequest && validMachineName(body.name)) suffix = '/nodes';
  else if (operation.type === 'node-revoke' && keys.length === 0 &&
      /^node_[a-f0-9]{32}$/.test(operation.node_id || '')) suffix = '/nodes/' + encodeURIComponent(operation.node_id) + '/revoke';
  if (!suffix) return null;
  const path = '/api/missions/' + encodeURIComponent(id) + suffix;
  return operation.path === undefined || operation.path === path ? path : null;
}
function machinePairComplete(id,pins) {
  return state.kind === 'mission' && state.id === id && !!state.mission &&
    array(state.mission.snapshot.nodes || state.mission.snapshot.tasks).every(task => pins.some(item => item.task_id === task.id));
}
function nodeCredentialKey(id,nodeId) { return id + ':' + nodeId; }
function publicNode(value, uncertain = false, enrollment = false) {
  const allowed = ['mission_id','node_id','request_id','name','drivers','models','status','created_at','revoked_at','execution_ready'];
  if (enrollment) allowed.push('secret');
  if (!value || typeof value !== 'object' || Array.isArray(value) || Object.keys(value).some(key => !allowed.includes(key)) ||
      !/^mission_[a-f0-9]{32}$/.test(value.mission_id || '') || !/^node_[a-f0-9]{32}$/.test(value.node_id || '') ||
      typeof value.request_id !== 'string' || !value.request_id || value.request_id.length > 200 ||
      typeof value.name !== 'string' || !value.name || !['ACTIVE','REVOKED'].includes(value.status) ||
      !Array.isArray(value.drivers) || !value.drivers.length || value.drivers.some(driver => typeof driver !== 'string') ||
      !Array.isArray(value.models) || !value.models.length || value.models.some(model => typeof model !== 'string') ||
      typeof value.created_at !== 'string' || (value.revoked_at !== null && typeof value.revoked_at !== 'string') ||
      (value.execution_ready !== undefined && typeof value.execution_ready !== 'boolean')) {
    throw new RequestError('机器库存记录不完整或身份异常；保留已读记录。',uncertain);
  }
  // Deliberately whitelist projection fields: no credential in public state.
  const projection = Object.fromEntries(allowed.filter(key => key !== 'secret' && key in value).map(key => [key,value[key]]));
  const wire = JSON.stringify(projection);
  const secrets = [...nodeSecretRedactions];
  if (enrollment && /^[a-f0-9]{64}$/.test(value.secret || '')) secrets.push(value.secret);
  if (secrets.some(secret => wire.includes(secret))) throw new RequestError('机器公开数据含凭据，保留原记录并等待核对。',uncertain);
  return projection;
}
function validatePin(pin,taskId,nodes,uncertain = false) {
  const wire = JSON.stringify(pin);
  if (typeof wire === 'string' && ((token && wire.includes(token)) || [...nodeSecretRedactions].some(secret => wire.includes(secret)))) {
    throw new RequestError('固定机器选择含凭据；保留原 pin，请核对读回。',uncertain);
  }
  if (pin && typeof pin === 'object' && !Array.isArray(pin) && pin.kind === 'local' && Object.keys(pin).length === 1) return pin;
  const registered = nodes.find(item => item.node_id === pin?.node_id);
  if (!pin || pin.kind !== 'remote' || pin.task_id !== taskId || !registered || pin.mission_id !== registered.mission_id ||
      !/^[a-f0-9]{64}$/.test(pin.task_hash || '') || !Number.isSafeInteger(pin.revision) || pin.revision < 1 ||
      typeof pin.request_id !== 'string' || !pin.request_id || typeof pin.execution_ready !== 'boolean' ||
      Object.keys(pin).some(key => !['kind','mission_id','task_id','node_id','task_hash','revision','request_id','execution_ready','created_at'].includes(key))) {
    throw new RequestError('固定机器选择读回异常；保留原 pin，请重新查询。',uncertain);
  }
  return pin;
}
async function readMachines(id,current) {
  const view = machineView(id), serial = ++view.serial, epoch = state.epoch, pendingAtRead = state.pending.get(machineKey(id));
  view.fresh = null; // Cached rows, an in-progress read and a failed half-pair never enable retry.
  if (current()) renderMachineAvailability();
  try {
    const [inventory,readback] = await Promise.all([
      api('/api/missions/' + encodeURIComponent(id) + '/nodes'),
      api('/api/missions/' + encodeURIComponent(id) + '/placements')]);
    if (serial !== view.serial) return;
    if (!inventory || inventory.mission_id !== id || !Array.isArray(inventory.nodes) || typeof inventory.execution_ready !== 'boolean' ||
        !readback || readback.mission_id !== id || !Array.isArray(readback.placements)) {
      throw new RequestError('机器或固定选择读回不完整；保留已读记录。');
    }
    const nodes = inventory.nodes.map(item => publicNode(item)), nodeIds = new Set(), tasks = new Set();
    for (const item of nodes) {
      if (nodeIds.has(item.node_id)) throw new RequestError('机器库存包含重复身份，请核对记录。');
      nodeIds.add(item.node_id);
    }
    const pins = readback.placements.map(item => {
      if (!item || typeof item.task_id !== 'string' || !item.task_id || tasks.has(item.task_id) ||
          Object.keys(item).some(key => !['task_id','placement'].includes(key))) throw new RequestError('固定选择任务编号重复或异常，请重新查询。');
      tasks.add(item.task_id); return {task_id:item.task_id,placement:validatePin(item.placement,item.task_id,nodes)};
    });
    if (state.kind === 'mission' && state.id === id && state.mission && !machinePairComplete(id,pins)) {
      throw new RequestError('机器与固定选择读回不完整；请完整查询当前固定子任务。');
    }
    // Commit only a fully validated pair; malformed reads never erase visible pins.
    view.nodes = nodes; view.placements = pins; view.loaded = true; view.error = '';
    const saved = state.pending.get(machineKey(id));
    const pending = saved === pendingAtRead && machineTransports.get(machineKey(id)) !== saved && machineIntentPath(id,saved) ? saved : null;
    view.fresh = {serial,epoch,pending:pendingAtRead};
    if (pending?.type === 'placement' && pins.some(item => item.task_id === pending.body?.task_id &&
        item.placement.kind === 'remote' && item.placement.node_id === pending.body?.node_id && item.placement.request_id === pending.request_id)) {
      clearPending(machineKey(id)); view.notice = '已读回同请求的固定机器选择；尚未启动或验收。';
    } else if (pending?.type === 'node-enroll' && nodes.some(item => item.request_id === pending.request_id && item.name === pending.body?.name)) {
      clearPending(machineKey(id)); view.notice = '已核对登记请求；首次凭据未收到时，请撤销后重新明确登记。';
    } else if (pending?.type === 'node-revoke' && nodes.some(item => item.node_id === pending.node_id && item.status === 'REVOKED')) {
      clearPending(machineKey(id)); nodeCredentials.delete(nodeCredentialKey(id,pending.node_id));
      view.notice = '核心库存已确认撤销。';
    }
  } catch (error) {
    if (serial !== view.serial) return;
    view.error = '机器与固定选择读取失败：' + clean(error.message);
  }
  if (current()) { renderMachines(); renderAvailability(); }
}
function machineOperationAllowed(id) {
  return state.kind === 'mission' && state.id === id && !!state.mission && machineView(id).loaded &&
    !machineView(id).error && state.connected && !state.loading && !state.loadError && !state.busy &&
    !state.pending.has(machineKey(id)) && !state.pending.has(pendingKey());
}
function assignmentAllowed(task,nodeId) {
  const view = machineView(state.id), pin = view.placements.find(item => item.task_id === task.id)?.placement;
  return machineOperationAllowed(state.id) && task.active !== false && !!pin && pin.kind === 'local' &&
    view.nodes.some(item => item.node_id === nodeId && item.status === 'ACTIVE') &&
    !['IN_FLIGHT','UNKNOWN','RECEIPTED','PASS'].includes(task.state || task.status) && task.verdict !== 'PASS';
}
function renderMachines() {
  $('machine-panel').hidden = state.kind !== 'mission' || !state.mission;
  if ($('machine-panel').hidden) return;
  const id = state.id, view = machineView(id), pending = state.pending.get(machineKey(id));
  $('machine-note').textContent = view.error || (pending ?
    [view.notice, machineTransports.get(machineKey(id)) === pending ? '原机器请求正在传输；读回等待原响应处理，不重复提交。' :
      !machineIntentPath(id,pending) ? '原机器请求记录格式异常；保留待核对记录，不提交其他请求。' :
      view.fresh && machinePairComplete(id,view.placements) ? '已完整查询，原机器请求仍待核对。可明确重试同一请求；不重新选择或自动提交。' :
      '机器操作结果待核对；先完整查询机器与固定选择，不自动重发。'].filter(Boolean).join(' ') : view.notice) ||
    (view.loaded ? '机器已登记不代表在线或原生登录；传输是否就绪以固定读回为准。选择不启动工作，Start 需单独确认。' : '正在只读查询机器与固定选择…');
  paint('machine-list',[id,view.nodes,machineOperationAllowed(id)],() => view.nodes.length ? view.nodes.map(item => {
    const row = node('article',undefined,'machine-row');
    row.append(node('strong',clean(item.name)),node('p',(item.status === 'ACTIVE' ? '已登记' : '已撤销') + ' · ' + item.node_id,'small muted'));
    const button = node('button','明确撤销登记','text-button small'); button.type = 'button'; button.dataset.revokeNode = item.node_id;
    button.disabled = !machineOperationAllowed(id) || item.status !== 'ACTIVE';
    button.onclick = () => revokeNode(id,item.node_id); row.append(button); return row;
  }) : [node('p',view.loaded ? '本任务尚无登记机器；未选择的子任务保留原默认本机。' : '库存待读取。','small muted')]);
  const tasks = array(state.mission.snapshot.nodes || state.mission.snapshot.tasks);
  paint('placement-list',[id,tasks,view.placements,view.nodes,machineOperationAllowed(id)],() => tasks.length ? tasks.map(task => {
    const row = node('article',undefined,'placement-row'); row.append(node('strong',task.title || task.id));
    const pin = view.placements.find(item => item.task_id === task.id)?.placement;
    const chosen = view.nodes.find(item => item.node_id === pin?.node_id);
    row.append(node('p',!pin ? '执行位置待读回；保留核心记录，不推测选择。' : pin.kind === 'local' ? '原默认本机 · 尚未固定远端机器' :
      '已固定：' + clean(chosen?.name || pin.node_id) + (chosen?.status === 'REVOKED' ? ' · 登记已撤销' : '') +
      (pin.execution_ready ? ' · 传输报告已就绪，执行与验收另查' : ' · 远端传输未就绪'),'small prose'));
    row.append(node('p','固定写入范围：' + (array(task.write_paths).join('、') || '见核心批准任务；范围待读取'),'small prose'));
    if (task.active === false) row.append(node('p','该任务已被新方案替代，保留原证据。','small muted'));
    if (pin?.kind === 'remote') row.append(node('p','原 pin · 修订 ' + pin.revision + ' · 请求 ' + clean(pin.request_id),'small muted'));
    if (pin?.kind === 'local' && task.active !== false) for (const item of view.nodes.filter(item => item.status === 'ACTIVE')) {
      const button = node('button','明确选择 ' + clean(item.name),'secondary small'); button.type = 'button';
      button.dataset.taskId = task.id; button.dataset.nodeId = item.node_id;
      button.disabled = !assignmentAllowed(task,item.node_id); button.onclick = () => assignPlacement(id,task.id,item.node_id); row.append(button);
    }
    return row;
  }) : [node('p','等待核心固定子任务；登记机器不自动规划或执行。','small muted')]);
  renderMachineAvailability();
}
function gatewayFieldsValid() {
  const url = /^http:\/\/(127\.0\.0\.1|localhost):([1-9][0-9]{0,4})$/.exec($('node-gateway-url').value);
  const host = /^(127\.0\.0\.1|localhost):([1-9][0-9]{0,4})$/.exec($('node-gateway-host').value);
  return !!(url && host && Number(url[2]) <= 65535 && Number(host[2]) <= 65535);
}
function exportNodeConfiguration() {
  if (state.kind !== 'mission' || !state.mission || !gatewayFieldsValid()) return null;
  const view = machineView(state.id), item = view.nodes.find(item => item.node_id === view.exportNode && item.status === 'ACTIVE');
  const secret = item && nodeCredentials.get(nodeCredentialKey(state.id,item.node_id));
  if (!secret) return null;
  return {schema:1,controller_mission_id:state.id,node_id:item.node_id,secret,
    gateway_url:$('node-gateway-url').value,gateway_host:$('node-gateway-host').value};
}
function renderMachineAvailability() {
  $('node-enroll').disabled = !machineOperationAllowed(state.id) || !$('node-name').value.trim();
  $('node-config-copy').disabled = !exportNodeConfiguration(); $('node-config-download').disabled = $('node-config-copy').disabled;
  const id = state.id, view = machineView(id), pending = state.pending.get(machineKey(id));
  const ticket = {id,pending,epoch:state.epoch,serial:view.serial};
  $('machine-retry').hidden = state.kind !== 'mission' || !state.mission || !pending;
  $('machine-retry').disabled = !machineRetryAllowed(ticket);
  $('machine-retry').onclick = () => retryMachine(ticket);
}
function machineRetryAllowed(ticket) {
  const {id,pending,epoch,serial} = ticket, view = machineView(id);
  return state.kind === 'mission' && state.id === id && state.epoch === epoch && !!pending &&
    state.pending.get(machineKey(id)) === pending && view.serial === serial && view.fresh?.serial === serial &&
    view.fresh.epoch === epoch && view.fresh.pending === pending && view.loaded && !view.error &&
    machinePairComplete(id,view.placements) && !!machineIntentPath(id,pending) &&
    !machineTransports.has(machineKey(id)) && state.connected && !state.loading && !state.loadError && !state.busy && !state.pending.has('mission:' + id);
}
async function retryMachine(ticket) {
  if (!machineRetryAllowed(ticket)) return;
  await machineMutation(ticket.id,ticket.pending,machineIntentPath(ticket.id,ticket.pending),true);
}
async function assignPlacement(id,taskId,nodeId) {
  if (state.kind !== 'mission' || state.id !== id) return;
  const task = array(state.mission?.snapshot.nodes || state.mission?.snapshot.tasks).find(item => item.id === taskId);
  if (!task || !assignmentAllowed(task,nodeId)) return;
  let uuid; try { uuid = requestId(); } catch (error) { machineView(id).notice = clean(error.message); renderMachines(); return; }
  await machineMutation(id,{type:'placement',request_id:uuid,body:{request_id:uuid,task_id:taskId,node_id:nodeId}},'/placements');
}
async function enrollNode() {
  const id = state.id; if (!machineOperationAllowed(id)) return;
  const name = $('node-name').value.trim();
  if (!validMachineName(name)) { machineView(id).notice = '请填写 1–200 UTF-8 字节的机器名称，不包含控制字符或凭据。'; renderMachines(); return; }
  let uuid; try { uuid = requestId(); } catch (error) { machineView(id).notice = clean(error.message); renderMachines(); return; }
  await machineMutation(id,{type:'node-enroll',request_id:uuid,body:{request_id:uuid,name}},'/nodes');
}
async function revokeNode(id,nodeId) {
  if (!machineOperationAllowed(id) || !machineView(id).nodes.some(item => item.node_id === nodeId && item.status === 'ACTIVE')) return;
  // Public operator route is /revoke, not a node-identity route or a DELETE alias.
  await machineMutation(id,{type:'node-revoke',node_id:nodeId,body:{}},'/nodes/' + encodeURIComponent(nodeId) + '/revoke');
}
function applyMachineResult(id,operation,data,retry = false) {
  const view = machineView(id), {body} = operation;
  if (operation.type === 'placement') {
    const pin = validatePin(data,body.task_id,view.nodes,true);
    if (pin.kind !== 'remote' || pin.node_id !== body.node_id || pin.request_id !== operation.request_id) throw new RequestError('选择回执与原请求不符，请查询固定 pin。',true);
    if (!retry) view.placements = view.placements.map(item => item.task_id === body.task_id ? {...item,placement:pin} : item);
    view.notice = '同请求的机器选择已固定；尚未启动或通过验收。';
  } else if (operation.type === 'node-enroll') {
    const item = publicNode(data,true,true);
    if (item.request_id !== operation.request_id || item.name !== body.name || item.status !== 'ACTIVE' ||
        (data.secret !== null && !/^[a-f0-9]{64}$/.test(data.secret || ''))) throw new RequestError('机器登记回执与原请求不符，请只读核对。',true);
    if (!retry) view.nodes = [...view.nodes.filter(row => row.node_id !== item.node_id),item];
    view.exportNode = item.node_id;
    if (data.secret !== null) {
      nodeSecretRedactions.add(data.secret); nodeCredentials.set(nodeCredentialKey(id,item.node_id),data.secret);
    }
    view.notice = data.secret === null ? '登记读回没有首次凭据；请撤销后重新明确登记，不推测原生登录。' :
      '已登记；首次凭据仅在本页私有内存。明确填写独立网关连接地址与实际 Host 后，可明确复制或下载。';
  } else if (operation.type === 'node-revoke') {
    const nodeId = operation.node_id;
    const item = publicNode(data,true);
    if (item.node_id !== nodeId || item.status !== 'REVOKED' ||
        item.mission_id !== view.nodes.find(row => row.node_id === nodeId)?.mission_id) throw new RequestError('撤销回执身份异常，请查询原机器记录。',true);
    if (!retry) { view.nodes = view.nodes.map(row => row.node_id === nodeId ? item : row); nodeCredentials.delete(nodeCredentialKey(id,nodeId)); }
    view.notice = '机器登记已撤销；原任务 pin 保留，未重新绑定或启动。';
  }
  if (retry) view.notice = '原请求已收到响应；仍等完整查询确认，未启动或通过验收。';
}
async function machineMutation(id,operation,route,retry = false) {
  const key = machineKey(id), view = machineView(id), epoch = state.epoch, busy = {type:operation.type,id};
  const path = retry ? route : '/api/missions/' + encodeURIComponent(id) + route;
  // Upgrade only the original fixed route for legacy eee intents, at explicit
  // retry. Preserve body/request_id/at, never allocate another operation id.
  if (!retry || operation.path === undefined || operation.mission_id === undefined) {
    operation = {...operation,path,mission_id:id,at:operation.at ?? Date.now()}; setPending(key,operation);
  }
  machineTransports.set(key,operation);
  view.serial++; view.fresh = null; state.busy = busy; state.version++; view.notice = ''; renderMachines(); renderAvailability();
  try {
    const data = await api(path,operation.body);
    if (state.pending.get(key) !== operation) return; // A late reply never applies to a newer pending generation.
    applyMachineResult(id,operation,data,retry);
    // Preserve the existing canonical success flow for initial operations.
    // Uncertain-operation retries resolve only through the matching GET pair.
    if (!retry) clearPending(key);
  } catch (error) {
    if (state.pending.get(key) === operation) {
      if (!retry && !error.uncertain) clearPending(key);
      view.notice = clean(error.message) + (retry || error.uncertain ? ' 结果待核对；完整查询后可明确重试同一请求，不自动提交。' : '');
    }
  } finally {
    if (machineTransports.get(key) === operation) machineTransports.delete(key);
    if (state.busy === busy) state.busy = null;
    if (state.kind === 'mission' && state.id === id && state.epoch === epoch) {
      state.version++;
      renderMachines(); renderAvailability(); await readSelected();
    } else renderAvailability();
  }
}
async function copyNodeConfiguration() {
  const config = exportNodeConfiguration(); if (!config) return;
  const id = state.id, epoch = state.epoch;
  try {
    if (!navigator.clipboard?.writeText) throw new Error('浏览器未开放剪贴板；可明确下载配置。');
    await navigator.clipboard.writeText(JSON.stringify(config,null,2)); machineView(id).notice = '首次配置已按你的明确操作复制；请按 0600 保存文件，勿粘贴到任务消息或诊断。';
  } catch (error) { machineView(id).notice = clean(error.message); }
  if (state.kind === 'mission' && state.id === id && state.epoch === epoch) renderMachines();
}
function downloadNodeConfiguration() {
  const config = exportNodeConfiguration(); if (!config) return;
  let url;
  try {
    url = URL.createObjectURL(new Blob([JSON.stringify(config,null,2)],{type:'application/json'}));
    const link = node('a'); link.href = url; link.download = 'node-agent-' + config.node_id + '.json';
    document.body.append(link); link.click(); link.remove();
    machineView(state.id).notice = '已明确交付首次配置；请将 credential 文件设为 0600，state 目录设为 0700。';
  } catch (error) { machineView(state.id).notice = clean(error.message); }
  finally { if (url) setTimeout(() => URL.revokeObjectURL(url),1000); }
  renderMachines();
}
function missionMetadata() { return state.missions.find(item => item.id === state.id) || {}; }
function missionChatView(id) {
  if (!state.missionChats.has(id)) state.missionChats.set(id,{linked:false,loading:false,error:'',chat:null,started:false,serial:0});
  return state.missionChats.get(id);
}
function matchingPreparedStart(chat,operation) {
  const started = chat?.placement_start;
  return !!(planningAcknowledged(chat) && chat.id === operation.body?.chat_id && chat.mission_id === operation.mission_id &&
    chat.placement_preparation.approval_hash === operation.body.approval_hash && started &&
    Object.keys(started).length === 3 && started.request_id === operation.request_id &&
    started.approval_hash === operation.body.approval_hash && started.status === 'ACK');
}
async function readMissionChat(id,current) {
  const view = missionChatView(id), serial = ++view.serial, pending = state.pending.get('mission:' + id);
  const ids = new Set(state.chats.filter(chat => chat.mission_id === id).map(chat => chat.id));
  if (view.chat?.mission_id === id) ids.add(view.chat.id);
  if (pending?.type === 'prepared-start') ids.add(pending.body?.chat_id);
  if (!ids.size && !state.chatsLoaded) {
    view.loading = true;
    await inventory(); // Readonly query, not a generic Start fallback.
    if (serial !== view.serial) return;
    for (const chat of state.chats.filter(chat => chat.mission_id === id)) ids.add(chat.id);
  }
  view.linked = ids.size > 0; view.loading = view.linked;
  if (!view.linked) { view.error = ''; return; }
  try {
    if (ids.size !== 1 || typeof [...ids][0] !== 'string') throw new RequestError('关联对话身份不明确，请核对原记录。');
    const chat = validateChat(await api('/api/chat?chat_id=' + encodeURIComponent([...ids][0])),[...ids][0]);
    if (serial !== view.serial) return;
    if (chat.mission_id !== id) throw new RequestError('关联对话与当前任务不一致，请核对原记录。');
    view.chat = chat; view.error = ''; upsertChat(chat);
    if (chat.placement_start?.status === 'ACK') view.started = true;
    if (pending?.type === 'prepared-start' && matchingPreparedStart(chat,pending)) {
      clearPending('mission:' + id);
      if (current()) state.controlNote = '已核对原聊天 Start 请求的 ACK；执行、验收与集成另查。';
    }
  } catch (error) {
    if (serial !== view.serial) return;
    view.error = '任务关联对话读取失败：' + clean(error.message);
  } finally {
    if (serial === view.serial) view.loading = false;
  }
  if (current()) {
    if (view.error) state.controlNote = view.error;
    else if (!planningAcknowledged(view.chat) && view.chat?.placement_preparation) state.controlNote = '原规划结果尚待核对；未取得精确 ACK，不提交 Start。';
    renderControlAvailability();
  }
}
function preparedStartAllowed(id) {
  const view = missionChatView(id), pending = state.pending.get('mission:' + id);
  if (!view.linked) return state.chatsLoaded && !state.chatIssues.length &&
    !state.chats.some(chat => chat.mission_id === id) && pending?.type !== 'prepared-start';
  if (view.loading || view.error || !planningAcknowledged(view.chat)) return false;
  if (pending?.type === 'prepared-start') {
    return pending.mission_id === id && pending.body?.chat_id === view.chat.id && pending.body?.allow_local_workers === true &&
      pending.body.request_id === pending.request_id && pending.body.approval_hash === view.chat.placement_preparation.approval_hash;
  }
  return view.chat.status === 'IDLE' && !view.started && !view.chat.placement_start;
}
async function startPreparedMission() {
  const id = state.id, epoch = state.epoch, view = missionChatView(id), key = 'mission:' + id;
  if (!missionControlAllowed('start') || !view.linked || !$('mission-permission').checked || $('mission-confirm').hidden) return;
  let operation = state.pending.get(key);
  if (!operation) {
    let uuid; try { uuid = requestId(); } catch (error) { state.controlNote = clean(error.message); render(); return; }
    operation = {type:'prepared-start',mission_id:id,request_id:uuid,at:Date.now(),
      body:{chat_id:view.chat.id,allow_local_workers:true,request_id:uuid,approval_hash:view.chat.placement_preparation.approval_hash}};
    setPending(key,operation); // Retain identity before transport, never recreate after UNKNOWN.
  }
  const busy = {type:'prepared-start',id}; state.busy = busy; state.version++; renderAvailability();
  try {
    const chat = validateChat(await api('/api/chat/start',operation.body),operation.body.chat_id,true);
    if (!matchingPreparedStart(chat,operation)) throw new RequestError('原 Start 请求结果尚待核对；仅查询原身份，不创建新请求。',true);
    view.chat = chat; view.started = true; upsertChat(chat); clearPending(key);
    if (state.kind === 'mission' && state.id === id && state.epoch === epoch) state.controlNote = '原聊天 Start 请求已受理；这不是执行完成或验收证明。';
  } catch (error) {
    if (!error.uncertain) clearPending(key);
    if (state.kind === 'mission' && state.id === id && state.epoch === epoch) state.controlNote = clean(error.message);
  } finally {
    if (state.busy === busy) state.busy = null;
    if (state.kind === 'mission' && state.id === id && state.epoch === epoch) {
      state.version++; $('mission-confirm').hidden = true; $('mission-permission').checked = false;
      render(); await readSelected();
    } else renderAvailability();
  }
}
function missionControlAllowed(action) {
  if (state.kind !== 'mission' || !state.mission || state.loading || state.busy || !state.connected || state.loadError) return false;
  const pending = state.pending.get(pendingKey());
  if (pending && action !== 'stop' && !(action === 'start' && pending.type === 'prepared-start' && preparedStartAllowed(state.id))) return false;
  if (state.pending.has(machineKey(state.id)) && action !== 'stop') return false;
  const snapshot = state.mission.snapshot, controller = state.mission.controller;
  if (snapshot.stopped || controller.stop_requested || snapshot.all_verified === true) return false;
  if (action === 'start') return !controller.running && preparedStartAllowed(state.id);
  if (action === 'pause') return controller.running && !snapshot.paused;
  if (action === 'resume') return !!snapshot.paused;
  return action === 'stop';
}
function renderControlAvailability() {
  for (const action of ['start','pause','resume','stop']) $('mission-' + action).disabled = !missionControlAllowed(action);
  $('mission-start-confirm').disabled = !missionControlAllowed('start') || !$('mission-permission').checked;
  $('confirm-stop').disabled = !missionControlAllowed('stop');
  $('mission-start').textContent = state.pending.get(pendingKey())?.type === 'prepared-start' ? '明确重试原 Start 请求' : '启动任务';
  if (state.kind === 'mission') {
    const view = missionChatView(state.id);
    const unknownMapping = !view.linked && (!state.chatsLoaded || state.chats.some(chat => chat.mission_id === state.id));
    $('control-note').textContent = unknownMapping ? '任务关联对话库存尚未完整核对；Start 保持关闭，请点击刷新进度重新查询。查询不会自动提交。' :
      state.pending.has(pendingKey()) ? '控制请求结果仍待核对。只查询核心状态，不重复提交。' : state.controlNote;
  }
}
function reconcileControl(data) {
  const key = 'mission:' + state.id, pending = state.pending.get(key); if (!pending) return;
  if (pending.type === 'prepared-start') return; // Running is not this chat/request ACK.
  const snapshot = data.snapshot, controller = data.controller;
  const resolved = pending.acknowledged === true || pending.action === 'start' && controller.running || pending.action === 'pause' && snapshot.paused ||
    pending.action === 'resume' && !snapshot.paused && (pending.was_paused || snapshot.resume_epoch > (pending.resume_epoch || 0)) ||
    pending.action === 'stop' && (snapshot.stopped || controller.stop_requested);
  if (resolved) {
    clearPending(key); state.controlNote = '已查询最新核心状态。控制回执不代表任务已通过验收。';
  }
}
async function control(action) {
  if (!missionControlAllowed(action)) return;
  if (action === 'start' && (!$('mission-permission').checked || $('mission-confirm').hidden)) return;
  if (action === 'stop' && $('stop-confirm').hidden) return;
  if (action === 'start' && missionChatView(state.id).linked) return startPreparedMission();
  const id = state.id, epoch = state.epoch;
  const operation = {type:'control',action,was_paused:state.mission.snapshot.paused,resume_epoch:state.mission.snapshot.resume_epoch,at:Date.now()};
  state.busy = {type:'control',id}; state.version++; renderAvailability();
  try {
    await api('/api/control',{mission_id:id,action,allow_local_workers:action === 'start' && $('mission-permission').checked});
    setPending('mission:' + id,{...operation,acknowledged:true});
    if (state.epoch === epoch) state.controlNote = '控制请求已接收，正在查询核心状态。这不是完成或验收证明。';
  } catch (error) {
    markUncertain('mission:' + id,operation,error);
    if (state.epoch === epoch) state.controlNote = error.uncertain ? '控制请求结果待确认。只查询状态，不自动重发。' : clean(error.message);
    else showGlobal(error.uncertain ? '任务控制结果待确认，请回到该任务查询。' : clean(error.message));
  } finally {
    state.busy = null; state.version++;
    if (state.epoch === epoch) {
      $('mission-confirm').hidden = true; $('mission-permission').checked = false; $('stop-confirm').hidden = true;
      render(); await readSelected();
    }
    await inventory();
  }
}
function recordData(record) {
  return record?.data && typeof record.data === 'object' && !Array.isArray(record.data) ? record.data : record || {};
}
function verificationChecks(verification) {
  if (Array.isArray(verification?.evidence?.checks)) return verification.evidence.checks;
  if (Array.isArray(verification?.metrics?.checks)) return verification.metrics.checks;
  return array(verification?.checks);
}
function verificationReview(verification) {
  return recordData(verification?.evidence?.review || verification?.metrics?.review || verification?.review);
}
function checkResult(check) {
  const data = recordData(check), classification = data.classification || {};
  return {id:data.id,check:data.check,status:classification.status || data.verdict || data.status,
    summary:text(classification.summary),reason:classification.reason_code};
}
function checkStatus(status) {
  return status === 'PASS' ? '检查通过' : status === 'FAIL' ? '检查未通过' : label(status,'等待检查判定');
}
function reviewStatus(status) {
  return status === 'PASS' ? '审查通过' : status === 'FAIL' ? '审查未通过' : label(status,'等待审查判定');
}
function detailLines(root, checks) {
  for (const check of array(checks)) {
    const result = checkResult(check);
    root.append(node('p',(result.check || result.id || '固定检查') + ' · ' + checkStatus(result.status) +
      (result.summary ? '：' + result.summary : ''),'prose'));
  }
}
function missionGraphElement(tag, attributes = {}, content) {
  const item = document.createElementNS('http://www.w3.org/2000/svg',tag);
  for (const [key,value] of Object.entries(attributes)) item.setAttribute(key,value);
  if (content !== undefined) item.textContent = clean(content);
  return item;
}
function missionGraphLines(task) {
  const checks = verificationChecks(task.verification).map(checkResult);
  const checked = checks.length > 0 && checks.every(check => check.status === 'PASS');
  const check = checked ? '检查通过' : checks.some(check => check.status === 'FAIL') ? '检查未通过' : '待检查';
  const review = verificationReview(task.verification);
  const scope = (task.active === false ? '历史记录' : '当前任务') + (task.stale ? ' · 证据已过期' : '') +
    (task.superseded_by ? ' · 替代为 ' + text(task.superseded_by) : '');
  return {checked,review,lines:[text(task.id),text(task.objective || task.id),
    '执行：' + label(task.state,'等待执行'),
    '固定检查：' + check + ' · 判定 ' + (task.verdict === 'PASS' ? 'PASS' : label(task.verdict,'尚未验收')),
    '独立审查：' + reviewStatus(review.verdict),scope]};
}
function renderMissionGraph(snapshot) {
  const owner = state.id, epoch = state.epoch;
  // The signature is a cleaned projection, not another task truth or request.
  try { paint('mission-graph',clean(JSON.stringify([owner,epoch,snapshot.revision,snapshot.nodes])),() => {
    const graph = $('mission-graph'), diagnostics = [], tasks = new Map();
    if (!Array.isArray(snapshot.nodes)) diagnostics.push('任务图格式异常：核心 nodes 不是列表。');
    for (const task of array(snapshot.nodes)) {
      if (!task || typeof task.id !== 'string' || !task.id || tasks.has(task.id)) {
        diagnostics.push('任务图无效：任务编号缺失或重复。'); continue;
      }
      tasks.set(task.id,task);
    }
    const dependencies = new Map(), following = new Map(), remaining = new Map(), depth = new Map();
    for (const id of tasks.keys()) { following.set(id,[]); depth.set(id,0); }
    for (const [id,task] of tasks) {
      const valid = [];
      if (!Array.isArray(task.depends_on)) diagnostics.push('依赖格式异常：' + id);
      else for (const dependency of task.depends_on) {
        if (typeof dependency !== 'string' || !tasks.has(dependency)) {
          diagnostics.push('依赖不存在或格式异常：' + id + ' ← ' + text(dependency)); continue;
        }
        valid.push(dependency); following.get(dependency).push(id);
      }
      dependencies.set(id,valid); remaining.set(id,valid.length);
    }
    const ready = [...tasks.keys()].filter(id => remaining.get(id) === 0);
    for (let index = 0; index < ready.length; index++) {
      const id = ready[index];
      for (const next of following.get(id)) {
        depth.set(next,Math.max(depth.get(next),depth.get(id) + 1));
        remaining.set(next,remaining.get(next) - 1);
        if (remaining.get(next) === 0) ready.push(next);
      }
    }
    if (ready.length !== tasks.size) {
      diagnostics.push('任务图无效：依赖包含循环，层级仅作异常读回。');
      const last = Math.max(0,...depth.values()) + 1;
      for (const id of tasks.keys()) if (remaining.get(id) > 0) depth.set(id,last);
    }
    const positions = new Map(), rows = new Map();
    for (const id of tasks.keys()) {
      const column = depth.get(id), row = rows.get(column) || 0;
      positions.set(id,{x:12 + column * 296,y:12 + row * 166}); rows.set(column,row + 1);
    }
    const width = tasks.size ? 24 + (Math.max(...depth.values()) + 1) * 296 - 46 : 280;
    const height = tasks.size ? 24 + Math.max(...rows.values()) * 166 - 18 : 24;
    graph.setAttribute('viewBox',`0 0 ${width} ${height}`);
    graph.style.width = width + 'px'; graph.style.height = height + 'px';
    const note = diagnostics.length ? diagnostics.join('；') : tasks.size ? '' : '尚无已绑定任务；请先读回控制器工作拆解。';
    $('mission-graph-note').textContent = clean(note);
    $('mission-graph-note').classList.toggle('error',diagnostics.length > 0);
    if (!tasks.size) return [];
    const defs = missionGraphElement('defs'), marker = missionGraphElement('marker',
      {id:'mission-graph-arrow',viewBox:'0 0 8 8',refX:8,refY:4,markerWidth:6,markerHeight:6,orient:'auto'});
    marker.append(missionGraphElement('path',{d:'M0 0 L8 4 L0 8 Z',class:'mission-graph-arrow'}));
    defs.append(marker);
    const children = [defs];
    for (const [id,deps] of dependencies) for (const dependency of deps) {
      const start = positions.get(dependency), end = positions.get(id);
      const x = start.x + 250, y = start.y + 74, mid = (x + end.x) / 2;
      children.push(missionGraphElement('path',{d:`M${x} ${y} C${mid} ${y} ${mid} ${end.y+74} ${end.x} ${end.y+74}`,
        class:'mission-graph-edge','data-from':dependency,'data-to':id,'marker-end':'url(#mission-graph-arrow)'}));
    }
    for (const [id,task] of tasks) {
      const p = positions.get(id), detail = missionGraphLines(task);
      const kind = task.active === false || task.stale ? 'history' : task.verdict === 'FAIL' ? 'failed' :
        detail.checked && detail.review.verdict === 'PASS' && task.state === 'SUCCEEDED' ? 'checked' :
        ['RUNNING','IN_FLIGHT'].includes(task.state) ? 'running' : 'waiting';
      const group = missionGraphElement('g',{class:'mission-graph-task graph-' + kind,
        'data-task-id':id,role:'button',tabindex:0,'aria-label':clean(detail.lines.join('；') + '；查看原固定详情')});
      group.dataset.focus = 'graph:' + owner + ':' + id;
      group.append(missionGraphElement('title',{},detail.lines.join('\n')),
        missionGraphElement('rect',{x:p.x,y:p.y,width:250,height:148,rx:8}));
      for (const [index,line] of detail.lines.entries()) group.append(missionGraphElement('text',
        {x:p.x+12,y:p.y+21+index*23,class:index === 0 ? 'graph-id' : index === 1 ? 'graph-name' : index === 5 ? 'graph-scope' : ''},
        previewText(clean(line),index === 1 ? 16 : 24)));
      const select = () => {
        if (state.kind !== 'mission' || state.id !== owner || state.epoch !== epoch) return;
        for (const card of $('task-list').querySelectorAll('details')) if (card.dataset.detail === id) {
          card.open = true; card.querySelector('summary')?.focus({preventScroll:true});
          card.scrollIntoView({block:'nearest',behavior:'auto'}); return;
        }
      };
      group.onclick = select;
      group.onkeydown = event => {
        if (!event.isComposing && event.keyCode !== 229 && (event.key === 'Enter' || event.key === ' ')) {
          event.preventDefault(); select();
        }
      };
      children.push(group);
    }
    return children;
  }); } catch {
    // paint caches before building; a failed graph must remain eligible for reread.
    state.signatures.delete('mission-graph');
    $('mission-graph').replaceChildren();
    const note = $('mission-graph-note');
    note.hidden = false;
    note.textContent = '任务图绘制失败。请刷新进度重读；核心任务与验收以原记录为准。';
    note.classList.add('error');
  }
}
function engineeringFactText(fact) {
  if (fact.state === 'RECORDED' || fact.state === 'FILTERED') return Array.isArray(fact.value) ? fact.value.join('、') : String(fact.value);
  return ({NOT_RECORDED:'未记录',REDACTED_AT_CAPTURE:'捕获时已隐藏',WITHHELD:'已隐藏',MALFORMED:'记录格式异常'})[fact.state];
}
function buildEngineeringResult(result) {
  // Count element + possible text node before creation; reserve room for a fixed
  // truncation note. This budget never changes or crops the Core graph.
  let created = 0;
  const exhausted = {}, blocked = new Set();
  const make = (tag,content,className) => {
    const safe = content === undefined ? undefined : clean(String(content));
    const cost = safe ? 2 : 1;
    if (created + cost > 2960) throw exhausted;
    created += cost;
    return node(tag,safe,className);
  };
  const root = make('div',undefined,'engineering-evidence');
  const line = (parent,content,full = false) => {
    const safe = clean(String(content)), chars = Array.from(safe);
    parent.append(make('p',!full && chars.length > 300 ? chars.slice(0,300).join('') + '…（显示已截断）' : safe,'prose'));
  };
  const disclosure = (parent,title,key) => {
    const item = make('details',undefined,'task-row'), summary = make('summary',title);
    item.dataset.detail = 'engineering-' + key; summary.dataset.focus = 'engineering-' + key;
    item.append(summary); parent.append(item); return item;
  };
  const overflow = (parent,name,count,shown) => {
    if (count > shown) line(parent,name + '显示 ' + shown + ' / ' + count + '，省略 ' + (count - shown) + ' 项（仅展示截断）。');
  };
  const hidden = source => {
    let pointer = source;
    while (pointer) {
      if (blocked.has(pointer)) return true;
      pointer = pointer.slice(0,pointer.lastIndexOf('/'));
    }
    return false;
  };
  const restrictArtifact = (deliverable,checks,review) => {
    if (deliverable) {
      const visible = new Set(deliverable.patch.rows.slice(0,40).map(row => row.source));
      for (const row of deliverable.patch.rows.slice(40)) if (!visible.has(row.source)) blocked.add(row.source);
    }
    for (const check of checks.slice(24)) blocked.add(check.id.source.slice(0,check.id.source.lastIndexOf('/')));
    for (const check of checks.slice(0,24)) for (const scalar of check.measurement.scalars.slice(16)) blocked.add(scalar.source);
    for (const reason of review.reasons.slice(12)) blocked.add(reason.source);
  };
  for (let index = 0; index < result.tasks.length; index++) {
    if (index >= 64) blocked.add('/snapshot/nodes/' + index);
    else { const task = result.tasks[index]; restrictArtifact(task.deliverable,task.checks,task.review); }
  }
  if (result.integration.result) {
    const proof = result.integration.result;
    restrictArtifact(proof.deliverable,proof.checks,proof.review);
  }
  const artifact = (parent,deliverable,checks,review,key) => {
    const delta = disclosure(parent,'具体改动 · 记录的 hash 增量',key + '-patch');
    if (!deliverable) line(delta,'尚无记录的候选增量。');
    else {
      line(delta,'候选 hash：' + engineeringFactText(deliverable.candidate_hash),true);
      line(delta,'原调用编号：' + engineeringFactText(deliverable.run_key));
      line(delta,'源增量行数：' + deliverable.patch.row_count + '；已隐藏路径：' + deliverable.patch.withheld_count + '。');
      for (const row of deliverable.patch.rows.slice(0,40)) {
        line(delta,(row.path === null ? '已隐藏路径' : row.path) + ' · ' + row.change_kind);
        line(delta,'before=' + (row.before === null ? '未记录' : row.before) + ' → after=' + (row.after === null ? '未记录' : row.after),true);
        line(delta,'来源：' + row.source);
      }
      overflow(delta,'增量',deliverable.patch.rows.length,40);
    }
    const measured = disclosure(parent,'检查与测量 · 与独立审查分开',key + '-checks');
    if (!checks.length) line(measured,'尚无记录的检查明细。');
    for (const check of checks.slice(0,24)) {
      measured.append(make('h4',engineeringFactText(check.check) + ' · ' + engineeringFactText(check.status)));
      line(measured,'检查编号：' + engineeringFactText(check.id));
      line(measured,'评估器说明：' + engineeringFactText(check.summary));
      line(measured,'候选 hash：' + engineeringFactText(check.candidate_hash),true);
      line(measured,'检查 hash：' + engineeringFactText(check.check_hash),true);
      for (const scalar of check.measurement.scalars.slice(0,16)) {
        line(measured,scalar.name + '=' + String(scalar.value)); line(measured,'来源：' + scalar.source);
      }
      line(measured,'源测量未输出（withheld）：' + check.measurement.withheld_count + '；源 scalar 省略：' + check.measurement.omitted_scalar_count + '；complete=' + String(check.measurement.complete) + '。');
      line(measured,'执行错误是否记录：' + (check.measurement.execution_error_recorded === null ? '未记录' : String(check.measurement.execution_error_recorded)));
      overflow(measured,'测量',check.measurement.scalars.length,16);
    }
    overflow(measured,'检查',checks.length,24);
    const reviewed = disclosure(parent,'独立审查 · 记录的理由与引用',key + '-review');
    line(reviewed,'审查裁决：' + engineeringFactText(review.verdict) + '；recorded=' + String(review.recorded) + '。裁决记录不是本页重新验收。');
    for (const reason of review.reasons.slice(0,12)) line(reviewed,engineeringFactText(reason));
    overflow(reviewed,'审查理由',review.reasons.length,12);
    for (const reference of review.evidence_refs) line(reviewed,'记录引用：' + engineeringFactText(reference));
    line(reviewed,'引用是否覆盖已记录检查：' + (review.references_cover_recorded_checks === null ? '未记录' : String(review.references_cover_recorded_checks)));
  };
  try {
    const statements = result.conclusion.statements;
    root.append(make('h4','目标问题'));
    const question = statements.find(item => item.template_id === 'Q01');
    line(root,question ? question.text : engineeringFactText(result.question.objective));
    root.append(make('h4','已记录的工程结论'));
    const conclusion = statements.find(item => /^C0[1-6]$/.test(item.template_id));
    line(root,conclusion ? conclusion.text : result.conclusion.stage);
    line(root,'捕获结论阶段：' + result.conclusion.stage + '。这是非原子捕获投影，不是验收，也不是实时进程终止证明。');
    // Prioritize bounded failure signals before task details can exhaust the shared budget.
    // The 50-row cap covers result and integration diagnostics; task-level ones get their own 50.
    const diagnostic = disclosure(root,'投影诊断 · 不改变核心判定','diagnostics');
    const general = [...result.diagnostics,...result.integration.diagnostics];
    const taskLevel = result.tasks.flatMap(task => task.diagnostics);
    if (!general.length && !taskLevel.length) line(diagnostic,'本次投影没有记录诊断；这不表示验收通过。');
    for (const item of general.slice(0,50)) line(diagnostic,item.code + ' · ' + item.section + ' · ' + item.source);
    overflow(diagnostic,'诊断',general.length,50);
    for (const item of taskLevel.slice(0,50)) line(diagnostic,item.code + ' · ' + item.section + ' · ' + item.source);
    overflow(diagnostic,'子任务诊断',taskLevel.length,50);
    for (let index = 0; index < Math.min(64,result.tasks.length); index++) {
      const task = result.tasks[index];
      const entry = disclosure(root,'子任务 · ' + previewText(engineeringFactText(task.objective),80),'task-' + index);
      line(entry,'任务编号：' + engineeringFactText(task.task_id));
      line(entry,'目标：' + engineeringFactText(task.objective));
      line(entry,'原固定验收：' + engineeringFactText(task.acceptance));
      line(entry,'记录阶段：' + task.stage + '；当前性：' + task.currentness.label + '。');
      line(entry,'工作流：' + engineeringFactText(task.workflow.state) + '；记录裁决：' + engineeringFactText(task.workflow.recorded_verdict));
      line(entry,'active=' + engineeringFactText(task.currentness.active) + '；stale=' + engineeringFactText(task.currentness.stale) + '；superseded_by=' + engineeringFactText(task.currentness.superseded_by));
      artifact(entry,task.deliverable,task.checks,task.review,'task-' + index);
    }
    overflow(root,'子任务',result.tasks.length,64);
    const integration = result.integration, integrated = disclosure(root,'集成 · 当前、历史与候选分开','integration');
    line(integrated,'捕获集成阶段：' + integration.stage + '；current=' + engineeringFactText(integration.current));
    line(integrated,'记录 revision：' + engineeringFactText(integration.lead_integration_revision) + '；continuation=' + engineeringFactText(integration.continuation_id) + '；evidence=' + engineeringFactText(integration.evidence_id));
    line(integrated,'行裁决：' + engineeringFactText(integration.recorded_verdict) + '；payload 裁决：' + engineeringFactText(integration.payload_verdict));
    if (integration.result) artifact(integrated,integration.result.deliverable,integration.result.checks,integration.result.review,'integration');
    for (const build of integration.builds) {
      line(integrated,'集成候选 · 非验收：' + engineeringFactText(build.key) + ' · ' + engineeringFactText(build.status));
      line(integrated,'候选 hash：' + engineeringFactText(build.candidate_hash),true);
    }
    const provenance = disclosure(root,'来源与局限 · AS_CAPTURED','provenance');
    line(provenance,'capture_basis=' + result.provenance.capture_basis + '；非原子捕获，不重新验证字节，不是验收。');
    line(provenance,'captured_at/event_cursor/event_head_hash 均未记录；pinned=false；bytes_reverified=false；projection_is_acceptance=false。');
    line(provenance,'记录 revision=' + engineeringFactText(result.provenance.revision) + '；resume_epoch=' + engineeringFactText(result.provenance.resume_epoch));
    line(provenance,'控制器记录 phase=' + engineeringFactText(result.control.phase) + '；project_verified=' + engineeringFactText(result.control.project_verified) + '；all_verified=' + engineeringFactText(result.control.all_verified));
    line(provenance,'已记录调用：' + result.attempts.length + '；待核对调用：' + result.control.unresolved.length + '；live_runtime=' + result.control.live_runtime + '。调用结束、检查、独立审查和集成是不同记录。');
    for (const limitation of result.limitations) line(provenance,limitation.code + '：' + limitation.text);
    const evidence = disclosure(root,'依据陈述 · 有界展示，指针仅作文本','statements');
    // Secondary prose must not reintroduce records omitted by the concrete
    // task/patch/check/scalar/reason display bounds.
    const eligible = statements.filter(item => !item.sources.some(hidden));
    for (const statement of eligible.slice(0,200)) {
      line(evidence,statement.template_id + ' · ' + statement.text);
      for (const source of statement.sources) line(evidence,'来源：' + source);
    }
    line(evidence,'源陈述 ' + statements.length + ' 条；本次有界显示 ' + Math.min(200,eligible.length) + ' 条；省略 ' + (statements.length - Math.min(200,eligible.length)) + ' 条。');
  } catch (error) {
    if (error !== exhausted) throw error;
    root.append(node('p','内容过多，已截断显示；原捕获与任务图保持完整。','small muted'));
  }
  return [root];
}
function renderEngineeringResult() {
  const deferred = state.kind === 'mission' && state.engineeringRead?.id === state.id && state.engineeringRead.epoch === state.epoch;
  $('engineeringResult').hidden = deferred;
  if (deferred) return;
  const selected = state.kind === 'mission' && state.engineering?.owner === state.id && state.engineering.epoch === state.epoch ? state.engineering : null;
  const notes = {
    OK:'OK · 工程结果来自本次非原子捕获，投影不是验收证明。',
    MISSING:'MISSING · 当前服务暂无工程结果（可能是旧版本）；任务图与进度保留。',
    INVALID:'INVALID · 工程结果格式校验失败，已清除旧结论；任务图与进度保留。',
    REJECTED:'REJECTED · 本次捕获未通过工程投影输入校验；任务图与进度保留。',
    FAILED:'FAILED · 本次工程结果投影失败；任务图与进度保留。'
  };
  const status = $('engineeringResultStatus');
  status.textContent = selected ? clean((selected.stale ? 'STALE · 以下是上次读取的工程结果，可能已过期。 ' : '') + notes[selected.status] + (selected.code ? '（' + selected.code + '）' : '')) : (state.kind === 'mission' ? '正在读取工程结果。' : '');
  try {
    paint('engineeringResultBody',selected ? [selected.owner,selected.epoch,selected.status,selected.stale,state.mission,selected.result,selected.code] : [state.kind,state.id,state.epoch,null],
      () => selected?.status === 'OK' ? buildEngineeringResult(selected.result) : []);
  } catch (error) {
    state.signatures.delete('engineeringResultBody');
    $('engineeringResultBody').replaceChildren();
    status.textContent = 'RENDER_FAILED · 工程结果展示失败，已清除局部内容；任务图与进度保留。';
  }
}
function renderMission() {
  const data = state.mission; if (!data) return;
  const snapshot = data.snapshot, controller = data.controller, meta = missionMetadata();
  $('view-title').textContent = '任务进度'; $('view-subtitle').textContent = state.id;
  const objective = snapshot.objective || meta.objective || '这次任务';
  $('mission-title').textContent = missionHeading(objective);
  $('mission-objective').textContent = objective;
  const verified = snapshot.all_verified === true;
  $('mission-status').textContent = verified ? '验收与集成已通过' : label(snapshot.phase,'等待核心状态') + (controller.running ? ' · 控制器运行中' : '');
  $('mission-status').classList.toggle('good',verified);
  $('acceptance-status').textContent = verified ? '核心快照已确认整项任务的验收与集成。' : '整项任务尚未确认通过验收。执行返回或控制请求已接收，都不代表完成。';
  $('mission-reason').textContent = clean(snapshot.reason || '') + (controller.error ? '\n控制器遇到问题：' + clean(controller.error.message || controller.error) : '') +
    (array(snapshot.unresolved).length ? '\n有 ' + snapshot.unresolved.length + ' 项调用结果待核对，不会自动重复调用。' : '');
  $('control-note').textContent = state.pending.has(pendingKey()) ? '控制请求结果仍待核对。只查询核心状态，不重复提交。' : state.controlNote;
  const linked = state.chats.find(chat => chat.mission_id === state.id);
  $('back-to-chat').hidden = !linked;
  const tasks = array(snapshot.nodes || snapshot.tasks);
  paint('task-list', tasks.map(task => ({...Object.fromEntries(['id','title','objective','acceptance','check','state','status','verdict','stale','active','attempts','depends_on','write_paths'].map(key => [key,task[key]])),checks:verificationChecks(task.verification).map(checkResult),review:verificationReview(task.verification)})), () => {
    if (!tasks.length) return [node('p','还没有已绑定的工作拆解。方案与任务状态以核心记录为准。','small muted')];
    return tasks.map((task,index) => {
      const row = node('details',undefined,'task-row'); row.dataset.detail = task.id || String(index);
      const summary = node('summary'); summary.dataset.focus = 'task-' + (task.id || index);
      const name = node('span',undefined,'task-label');
      name.append(node('span',task.title || task.objective || task.id || '待命名任务','task-title'),node('span',
        label(task.state || task.status,'等待执行') + ' · ' + (task.stale ? '证据已过期' : label(task.verdict,'尚未验收')) +
        (task.active === false ? ' · 已被新方案替代' : ''),'task-meta'));
      summary.append(name); row.append(summary);
      const detail = node('div',undefined,'task-detail');
      detail.append(node('p','验收要求：' + (text(task.acceptance) || '见已批准的固定检查'),'prose'));
      if (task.id) detail.append(node('p','任务编号：' + task.id,'prose'));
      if (task.check) detail.append(node('p','固定检查：' + task.check,'prose'));
      detail.append(node('p','固定写入范围：' + (array(task.write_paths).join('、') || '见核心批准任务；范围待读取'),'prose'));
      if (array(task.depends_on).length) detail.append(node('p','依赖：' + task.depends_on.join('、'),'prose'));
      if (task.attempts !== undefined) detail.append(node('p','保留的尝试：' + task.attempts));
      detailLines(detail,verificationChecks(task.verification));
      const review = verificationReview(task.verification);
      if (review.verdict) detail.append(node('p','独立审查：' + reviewStatus(review.verdict) + ' · ' + array(review.reasons).join('；'),'prose'));
      row.append(detail); return row;
    });
  });
  renderMissionGraph(snapshot);
  renderProgress(snapshot,tasks); renderRSI(snapshot); renderEvents(); renderMissionInbox(); renderMachines();
  const fingerprint = JSON.stringify([meta.source,checkNamesForMission()]);
  if (state.missionConfirmFingerprint && state.missionConfirmFingerprint !== fingerprint) {
    $('mission-confirm').hidden = true; $('mission-permission').checked = false;
  }
  state.missionConfirmFingerprint = fingerprint;
  if (!missionControlAllowed('start') && !state.busy) { $('mission-confirm').hidden = true; $('mission-permission').checked = false; }
}
function missionHeading(objective) {
  const confirmed = text(objective).split('Operator-confirmed conversation plan:\n')[1];
  const summary = confirmed ? confirmed.split('\nArchitecture:\n')[0].split('。')[0] : objective;
  return previewText(summary,100);
}
function threadEntry(title, lines) {
  const entry = node('article',undefined,'thread-entry'); entry.append(node('h4',title));
  for (const line of lines) if (line) entry.append(node('p',line,'prose'));
  return entry;
}
function renderRSI(snapshot) {
  const trials = snapshot.procedure_trials || {}, history = snapshot.rsi || {}, active = history.active_id || snapshot.procedure?.id;
  const reports = array(trials.paired_trial_results).length ? array(trials.paired_trial_results) : array(trials.results);
  paint('rsi-evidence',[snapshot.rsi_configuration,snapshot.procedure,trials,history],() => {
    const rows = [threadEntry('当前策略',[snapshot.procedure?.version !== undefined ? '已采用流程版本 v' + snapshot.procedure.version : '当前流程版本待读取。',
      active ? '策略编号：' + active : '', '工程验收、对照评估与策略晋升是三个独立状态；不代表模型能力提升。'])];
    if (!reports.length) rows.push(threadEntry('baseline / candidate → holdout',[
      trials.status && trials.status !== 'IDLE' ? '评估状态：' + label(trials.status) : '尚无已完成的对照评估。',
      '先产生有工程证据的候选策略，再运行固定 search 对照和独立 holdout。'
    ]));
    if (trials.status && trials.status !== 'IDLE') for (const child of array(trials.trial_children)) {
      const registration = recordData(array(child.registrations).find(record => record.category === 'paired_trial_children') || array(child.registrations)[0]);
      const name = (registration.split || 'trial') + ' · ' + (registration.arm || '子任务');
      rows.push(threadEntry(name,[child.read_status === 'OK' ? label(child.phase) + ' · ' +
        (Number.isInteger(child.reservations) ? '已记录 ' + child.reservations + ' 次调用' : '调用数待核对') : '子任务记录待读取，调用数未知。',
        child.error ? '读取诊断：' + clean(text(child.error)) : '', '这是调度进度，不是验收或晋升结论。']));
    }
    const results = new Map(reports.map(record => [record.key,recordData(record)]));
    for (const report of results.values()) {
      const activated = report.status === 'PROMOTED' && report.promoted === true && active === report.candidate_id;
      const conclusion = activated ? '已晋升并采用候选策略' : report.status === 'PROMOTED' ? '历史晋升已记录，当前采用状态见上方策略编号' :
        report.status === 'ELIGIBLE' ? '评估门槛已满足，尚未晋升' : report.status === 'NONPROMOTION' ? '未晋升，保留既有策略' : '评估尚未确立：' + label(report.status);
      const lines = [report.candidate_id ? '候选策略：' + report.candidate_id : '',
        '指标：真实调用预留数（不是模型自报分数）'];
      const pairs = new Map();
      for (const arm of array(report.arms)) {
        const key = arm.pair_id || JSON.stringify([arm.split,arm.case_id || 'single']);
        if (!pairs.has(key)) pairs.set(key,{split:arm.split,case_id:arm.case_id});
        pairs.get(key)[arm.arm] = arm;
      }
      for (const pair of pairs.values()) {
        const left = pair.baseline?.proof, right = pair.candidate?.proof;
        const countsKnown = Number.isInteger(left?.invocations) && Number.isInteger(right?.invocations);
        const measured = countsKnown ? 'baseline ' + left.invocations + ' 次 → candidate ' + right.invocations + ' 次；节省 ' + (left.invocations - right.invocations) + ' 次' : '调用与验收证据尚未齐备';
        lines.push((pair.split === 'holdout' ? 'holdout · 独立留出' : 'search · 固定对照') + (pair.case_id ? ' / ' + text(pair.case_id) : '') + '：' + measured);
        if (left || right) {
          const missing = [left,right].some(proof => !proof || Object.values(proof.attestation || {}).includes('MISSING'));
          lines.push(missing ? '运行模型证明不完整；仅作为请求模型匹配的流程试验。' : '模型身份范围以原始运行回执为准。');
          lines.push([left,right].every(proof => proof?.cost_status === 'METERED') ? '费用已有计量记录，见原始证据。' : '费用计量不完整，不将缺失值计为 0。');
        }
      }
      const reason = report.error?.message || report.error || report.assessment?.reason;
      if (reason) lines.push('判定依据：' + clean(text(reason)));
      if (!pairs.size) lines.push('尚无可核对的 baseline / candidate 配对证据。');
      rows.push(threadEntry(conclusion,lines));
    }
    return rows;
  });
}
function renderProgress(snapshot,tasks) {
  const runs = array(snapshot.attempts || snapshot.runs);
  const last = recordData(runs.at(-1));
  const runSummary = {count:runs.length,status:last.receipt?.status || last.status};
  const diagnoses = array(snapshot.diagnoses).map(record => {
    const data = recordData(record);
    return {key:record.key,classification:data.classification || data.category,reasons:array(data.reasons)};
  });
  const integration = snapshot.integration || {}, proof = integration.evidence?.payload;
  const taskScope = task => (task.active === false ? '历史任务 · ' : '当前任务 · ') + (task.id || previewText(task.title || task.objective,30));
  const tests = [];
  for (const task of tasks) for (const check of verificationChecks(task.verification)) {
    tests.push({...checkResult(check),scope:taskScope(task)});
  }
  for (const check of verificationChecks(proof)) tests.push({...checkResult(check),scope:'集成验收'});
  for (const check of array(snapshot.tests || snapshot.test_evidence)) tests.push({...checkResult(check),scope:'固定检查记录'});
  const reviews = array(snapshot.reviews || snapshot.review_evidence).map(record => {
    const review = recordData(record), runKey = review.run_key || record.key;
    const task = runKey ? tasks.find(item => verificationReview(item.verification).run_key === runKey) : null;
    const integrationReview = verificationReview(proof);
    const scope = task ? taskScope(task) : integrationReview.run_key && integrationReview.run_key === runKey ? '集成审查' : '审查记录';
    return {key:record.key,verdict:review.verdict,reasons:array(review.reasons),scope};
  });
  if (!reviews.length) {
    for (const task of tasks) {
      const review = verificationReview(task.verification);
      if (review.verdict) reviews.push({verdict:review.verdict,reasons:array(review.reasons),scope:taskScope(task)});
    }
    const review = verificationReview(proof);
    if (review.verdict) reviews.push({verdict:review.verdict,reasons:array(review.reasons),scope:'集成审查'});
  }
  const integrationSummary = {verified:snapshot.all_verified === true,current:integration.current === true,
    verdict:integration.evidence?.verdict || proof?.verdict,status:integration.status};
  const procedureVersion = snapshot.procedure?.version;
  const hasProcedure = !!snapshot.procedure || !!snapshot.rsi;
  paint('progress-thread',[runSummary,diagnoses,reviews,tests,integrationSummary,procedureVersion,hasProcedure],() => {
    const rows = [];
    rows.push(threadEntry('实施与尝试',[runSummary.count ? '已保留 ' + runSummary.count + ' 次调用记录，失败与重试不会被覆盖。' : '当前快照暂未提供实施调用记录。',
      runSummary.count ? '最近一次：' + label(runSummary.status,'等待调用回执') + '。调用结束不等于验收通过。' : '']));
    if (diagnoses.length) for (const diagnosis of diagnoses.slice(-3)) rows.push(threadEntry('根因分析 · ' + label(diagnosis.classification,'待分类'),diagnosis.reasons));
    else rows.push(threadEntry('根因分析',['有问题时会保留诊断与修订依据；当前快照没有诊断记录。']));
    if (tests.length) {
      const lines = tests.slice(-12).map(check => check.scope + ' / ' + (check.check || check.id || '固定检查') + ' · ' + checkStatus(check.status));
      lines.push('检查判定与独立审查分开记录。历史检查通过，不代表历史审查也通过。');
      rows.push(threadEntry('固定验收检查',lines));
    } else rows.push(threadEntry('固定验收检查',['当前快照暂未提供检查明细，可在诊断信息中核对原始证据。']));
    rows.push(threadEntry('独立审查',reviews.length ? reviews.slice(-8).map(review => review.scope + ' · ' + reviewStatus(review.verdict) +
      (review.reasons.length ? '：' + review.reasons.join('；') : '')) : ['当前快照暂未提供独立审查明细。']));
    const integrationLine = integrationSummary.verified ? '整项任务验收与集成已通过，核心快照已统一确认。' :
      integrationSummary.current ? '当前集成证据有效；整项任务尚未确认通过验收。' : '当前集成证据尚未确认有效。';
    rows.push(threadEntry('集成验证',[integrationLine,
      integrationSummary.verdict ? '集成验收：' + label(integrationSummary.verdict,'等待判定') :
        integrationSummary.status ? '集成状态：' + label(integrationSummary.status) : '当前快照暂未提供集成验收明细。'
    ]));
    if (hasProcedure) rows.push(threadEntry('流程改进',[procedureVersion ? '当前流程版本：' + procedureVersion : '流程评估与工程验收分开记录。','提议或评估不表示改进已被采用。']));
    return rows;
  });
}

const eventLabels = {
  lead_initialized:'任务已绑定，等待明确开工', lead_plan:'实施方案已有新记录', lead_plans:'实施方案已有新记录',
  lead_diagnoses:'记录了一次根因分析', lead_reviews:'记录了一次独立审查', lead_integrations:'记录了一次集成尝试',
  lead_state:'核心状态有更新', lead_runtime_errors:'控制器记录了运行问题', lead_diagnosis_errors:'根因分析遇到了问题',
  lead_console_control:'已记录控制请求，等待状态确认', lead_console_ack:'控制请求已有回执，不代表验收通过',
  verdict:'验收判定有更新', lead_run:'模型调用记录有更新'
};
function renderEvents() {
  const known = state.events.filter(event => eventLabels[event.type]).slice(-8);
  $('event-section').hidden = !known.length;
  paint('event-thread',known,() => known.map(event => threadEntry(eventLabels[event.type],[event.seq !== undefined ? '记录 #' + event.seq : ''])));
  if (state.drawer === 'debug') renderDebug();
}
function render() {
  const isChat = state.kind === 'chat', isMission = state.kind === 'mission';
  $('welcome').hidden = isMission || (isChat && (state.loading || !!state.loadError || array(state.chat?.messages).length > 0 || !!state.chat?.proposal));
  $('chat-view').hidden = !isChat || !state.chat;
  $('mission-view').hidden = !isMission || !state.mission;
  $('composer-wrap').hidden = false;
  $('load-state').hidden = !state.loading;
  $('load-error').hidden = !state.loadError;
  $('load-error-text').textContent = state.loadError + ' 已保留本页输入，重新读取不会再次提交。';
  if (isChat) renderChat();
  if (isMission) renderMission();
  renderConnection(); renderLists(); renderAvailability();
  if (state.drawer === 'debug') renderDebug();
  renderEngineeringResult();
}
function scrollLatest() {
  const area = $('scroll-area');
  if (state.forceScroll || area.scrollHeight - area.scrollTop - area.clientHeight < 140) {
    requestAnimationFrame(() => { area.scrollTop = area.scrollHeight; $('jump-latest').hidden = true; });
  } else $('jump-latest').hidden = false;
  state.forceScroll = false;
}
function readableRule(value) {
  if (typeof value === 'string') return value;
  if (value === null || value === undefined) return '见已批准的验收文件';
  if (typeof value !== 'object') return String(value);
  if (Array.isArray(value)) return value.map(readableRule).join('；');
  if (Array.isArray(value.all)) return '全部满足：' + value.all.map(readableRule).join('；');
  if (Array.isArray(value.any)) return '任一满足：' + value.any.map(readableRule).join('；');
  if (value.not) return '不满足：' + readableRule(value.not);
  if (value.path) {
    const ops = {eq:'等于',ne:'不等于',gt:'大于',gte:'至少',lt:'小于',lte:'至多',in:'属于',exists:'存在',contains:'包含'};
    const expected = typeof value.value === 'object' ? array(value.value).map(text).join('、') || '已绑定的结构值' : text(value.value);
    return text(value.path) + ' ' + (ops[value.op] || text(value.op)) + (expected ? ' ' + expected : '');
  }
  return '已绑定的固定规则，详见验收文件';
}
function renderChecks(checks) {
  paint('context-checks',checks,() => {
    if (!checks.length) return [node('p','验收项目尚未读到。绑定文件后，服务会提供固定条件摘要。','small muted')];
    return checks.map(check => {
      const row = node('div',undefined,'check-row');
      row.append(node('strong',check.id || check.check || '固定检查'),node('p','通过条件：' + readableRule(check.pass_if)),node('p','失败条件：' + readableRule(check.fail_if)));
      return row;
    });
  });
}
function syncSettings(force) {
  if (state.drawer !== 'settings') return;
  const missionMode = state.kind === 'mission', owner = state.kind + ':' + state.id;
  const chat = state.chat;
  const source = missionMode ? missionMetadata().source || '' : chat?.source || '';
  const spec = missionMode ? '' : chat?.spec_path || '';
  if (force || state.contextOwner !== owner) {
    state.contextOwner = owner; state.contextDirty = false;
    $('source').value = source; $('spec-path').value = spec;
    state.contextValues = {source,spec_path:spec}; $('context-error').hidden = true; $('context-save-state').textContent = '';
  } else if (!state.contextDirty && (state.contextValues.source !== source || state.contextValues.spec_path !== spec)) {
    $('source').value = source; $('spec-path').value = spec; state.contextValues = {source,spec_path:spec};
  }
  const locked = missionMode || !!chat?.mission_id;
  $('source').readOnly = locked; $('spec-path').readOnly = locked;
  $('reuse-project').hidden = locked;
  renderExistingProjects();
  $('settings-intro').textContent = locked ? '此任务已经绑定固定验收。这里仅显示工程；验收证据见进度页，设置不会修改已绑定任务。' : '先聊想法也可以。开工前，再绑定工程和已经批准的验收文件。';
  const requested = chat?.model?.requested, actual = chat?.model?.actual;
  $('settings-model').textContent = actual ? '运行记录的实际模型：' + actual + (requested ? '。请求模型：' + requested : '') : requested ? '请求模型：' + requested + '。实际运行模型尚未由回执确认。' : '尚无对话运行模型记录。';
  renderChecks(missionMode ? checkNamesForMission().map(id => ({id})) : checksForChat(chat));
  renderAvailability();
}
async function prepareDirectory() {
  if (!canPrepareDirectory()) return;
  const id = state.id, epoch = state.epoch; let uuid;
  try { uuid = requestId(); } catch (error) { state.chatNotice = error.message; render(); return; }
  state.busy = {type:'directory',id}; state.version++; renderAvailability();
  try {
    const chat = validateChat(await api('/api/chat/prepare_directory',{chat_id:id,request_id:uuid}),id,true);
    upsertChat(chat); clearPending('chat:' + id);
    if (state.epoch === epoch && state.id === id) {
      state.chatNotice = chat.directory_preparation?.detail || '已查询目录准备结果。';
      applyChat(chat);
    }
  } catch (error) {
    markUncertain('chat:' + id,{type:'directory',request_id:uuid},error);
    if (state.epoch === epoch) state.chatNotice = clean(error.message);
    else showGlobal(error.uncertain ? '目录准备结果待确认，请回到原对话查询记录。' : clean(error.message));
  } finally {
    state.busy = null; state.version++; render();
    if (state.kind === 'chat' && state.id === id) await readSelected();
  }
}
async function saveContext(event) {
  event.preventDefault(); if ($('save-context').disabled) return;
  const source = $('source').value.trim(), spec_path = $('spec-path').value.trim();
  if (spec_path && !spec_path.startsWith('/')) {
    $('context-error').hidden = false; $('context-error').textContent = '请填写已批准验收文件的绝对路径，以 / 开头。'; $('spec-path').focus(); return;
  }
  let id = state.chat?.id; const epoch = state.epoch, drawerEpoch = state.contextEpoch;
  state.busy = {type:'context',id}; state.version++; renderAvailability();
  $('context-error').hidden = true; $('context-save-state').textContent = '正在保存…';
  try {
    if (!id) {
      let created;
      try { created = await createChat(); }
      catch (error) { markUncertain('create',{type:'create'},error); throw error; }
      id = created.id;
      if (state.epoch !== epoch) { showGlobal('对话已建立，设置尚未提交。请打开新对话后继续。'); return; }
      saveDraft(); const draft = state.drafts.get(draftKey('welcome','')) || '';
      state.kind = 'chat'; state.id = id; state.epoch++; state.chat = created;
      state.drafts.set(draftKey('chat',id),draft); state.contextOwner = 'chat:' + id; upsertChat(created);
    }
    try {
      const chat = validateChat(await api('/api/chat/context',{chat_id:id,source,spec_path}),id,true); upsertChat(chat);
      if (state.kind === 'chat' && state.id === id) {
        state.contextDirty = false; applyChat(chat);
        if (state.contextEpoch === drawerEpoch) { syncSettings(true); $('context-save-state').textContent = '已保存'; }
        say('工程与验收设置已保存。');
      }
    } catch (error) { markUncertain('chat:' + id,{type:'context',source,spec_path},error); throw error; }
  } catch (error) {
    if (state.contextEpoch === drawerEpoch) {
      $('context-save-state').textContent = ''; $('context-error').hidden = false;
      $('context-error').textContent = error.uncertain ? '保存结果待确认。先查询记录，不会自动再次保存。' : clean(error.message);
    }
    if (state.pending.has('create')) showGlobal('对话创建结果待确认，设置尚未发送。请先核对侧栏记录。',true);
  } finally {
    state.busy = null; state.version++; render();
    if (id && state.kind === 'chat' && state.id === id) await readSelected();
    renderLists();
  }
}
function renderExistingProjects() {
  const select = $('existing-project'), selected = select.value;
  paint('existing-project',state.missions.map(mission => ({id:mission.id,objective:mission.objective,source:mission.source})),() => {
    const placeholder = node('option',state.missions.length ? '选择一个工程与验收方案…' : '暂无可复用的工程，可手动填写路径'); placeholder.value = '';
    return [placeholder,...state.missions.map(mission => {
      const option = node('option',mission.objective || '已批准的工程'); option.value = mission.id;
      option.title = mission.source || ''; return option;
    })];
  });
  if (state.missions.some(mission => mission.id === selected)) select.value = selected;
  renderAvailability();
}
async function attachMission() {
  if ($('attach-mission').disabled) return;
  const mission_id = $('existing-project').value, project = state.missions.find(mission => mission.id === mission_id);
  if (!project) return;
  let id = state.chat?.id; const epoch = state.epoch, drawerEpoch = state.contextEpoch;
  const before_spec = state.chat?.spec_path || '';
  state.busy = {type:'attach',id}; state.version++; renderAvailability();
  $('attach-state').textContent = '正在绑定工程与固定验收…'; $('context-error').hidden = true;
  try {
    if (!id) {
      let created;
      try { created = await createChat(); }
      catch (error) { markUncertain('create',{type:'create'},error); throw error; }
      id = created.id;
      if (state.epoch !== epoch) { showGlobal('对话已建立，工程尚未绑定。请从侧栏打开后继续。'); return; }
      saveDraft(); const draft = state.drafts.get(draftKey('welcome','')) || '';
      state.kind = 'chat'; state.id = id; state.epoch++; state.chat = created;
      state.drafts.set(draftKey('chat',id),draft); state.contextOwner = 'chat:' + id; upsertChat(created);
    }
    try {
      const chat = validateChat(await api('/api/chat/attach_mission',{chat_id:id,mission_id}),id,true); upsertChat(chat);
      if (state.kind === 'chat' && state.id === id) {
        state.contextDirty = false; applyChat(chat);
        if (state.contextEpoch === drawerEpoch) { syncSettings(true); $('attach-state').textContent = '已绑定，尚未开工。原目标、交付物与约束会保留。'; }
        say('工程与固定验收已绑定，没有启动任务。');
      }
    } catch (error) { markUncertain('chat:' + id,{type:'attach',source:project.source,before_spec},error); throw error; }
  } catch (error) {
    if (state.contextEpoch === drawerEpoch) $('attach-state').textContent = error.uncertain ? '绑定结果待确认。先查询当前记录，不会自动重复绑定。' : clean(error.message);
    if (state.pending.has('create')) showGlobal('新对话创建结果待确认，工程尚未绑定。请先核对列表。',true);
  } finally {
    state.busy = null; state.version++; render();
    if (id && state.kind === 'chat' && state.id === id) await readSelected();
    renderLists();
  }
}
function drawerElement() { return state.drawer ? $(state.drawer === 'sidebar' ? 'sidebar' : state.drawer) : null; }
function openDrawer(name) {
  if (state.drawer === name) return;
  const previousFocus = state.returnFocus || document.activeElement;
  closeDrawer(false); state.drawer = name; state.returnFocus = previousFocus; state.contextEpoch++;
  const panel = drawerElement();
  if (name === 'sidebar') {
    $('sidebar').classList.add('open'); $('sidebar').setAttribute('role','dialog'); $('sidebar').setAttribute('aria-modal','true');
    $('menu-toggle').setAttribute('aria-expanded','true');
  } else {
    panel.hidden = false; $('sidebar').inert = true;
    if (name === 'settings') { $('open-settings').setAttribute('aria-expanded','true'); syncSettings(true); }
    if (name === 'debug') renderDebug();
  }
  $('backdrop').hidden = false; $('workspace').inert = true;
  const target = panel.querySelector('button:not([disabled]),input:not([readonly]),a');
  if (target) target.focus({preventScroll:true});
}
function closeDrawer(restoreFocus = true) {
  if (!state.drawer) return;
  if (state.drawer === 'sidebar') {
    $('sidebar').classList.remove('open'); $('sidebar').removeAttribute('role'); $('sidebar').removeAttribute('aria-modal');
  } else drawerElement().hidden = true;
  $('sidebar').inert = false; $('workspace').inert = false; $('backdrop').hidden = true;
  $('menu-toggle').setAttribute('aria-expanded','false'); $('open-settings').setAttribute('aria-expanded','false');
  const returnFocus = state.returnFocus; state.drawer = null; state.returnFocus = null; state.contextEpoch++;
  if (restoreFocus && returnFocus?.isConnected && !returnFocus.closest('[hidden]')) returnFocus.focus({preventScroll:true});
}
function renderDebug() {
  $('debug-state').textContent = clean(state.kind === 'mission' ? state.mission?.snapshot : state.chat);
  $('debug-events').textContent = clean(state.events);
  $('debug-controls').textContent = clean(state.mission?.controls || []);
  $('debug-requests').textContent = clean({last_read:state.lastRead,pending:[...state.pending],storage_issue:storageIssue,requests:state.traces});
  $('debug-issues').textContent = clean({chats:state.chatIssues,missions:state.issues});
}
$('new-chat').onclick = newChat;
$('composer-form').onsubmit = event => { event.preventDefault(); sendMessage(); };
$('composer-input').addEventListener('input',() => { saveDraft(); resizeComposer(); renderAvailability(); });
$('composer-input').addEventListener('compositionstart',() => { state.composing = true; });
$('composer-input').addEventListener('compositionend',() => { state.composing = false; });
$('composer-input').addEventListener('keydown',event => {
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing && !state.composing && event.keyCode !== 229) {
    event.preventDefault(); if (canSend()) sendMessage();
  }
});
for (const button of document.querySelectorAll('[data-prompt]')) button.onclick = () => {
  $('composer-input').value = button.dataset.prompt; saveDraft(); resizeComposer(); renderAvailability(); $('composer-input').focus();
};
for (const id of ['open-settings','composer-settings','context-action']) $(id).onclick = () => openDrawer('settings');
for (const id of ['open-debug','mission-debug','settings-debug']) $(id).onclick = () => openDrawer('debug');
for (const id of ['close-settings','close-debug','sidebar-close','backdrop']) $(id).onclick = () => closeDrawer();
$('menu-toggle').onclick = () => openDrawer('sidebar');
$('context-form').onsubmit = saveContext;
$('attach-mission').onclick = attachMission;
$('existing-project').onchange = renderAvailability;
for (const id of ['source','spec-path']) $(id).addEventListener('input',() => { state.contextDirty = true; $('context-save-state').textContent = '尚未保存'; });
$('review-plan').onclick = reviewPlan;
$('prepare-directory').onclick = prepareDirectory;
$('preflight-settings').onclick = () => {
  openDrawer('settings'); $('manual-context').open = true;
  (state.chat?.source ? $('spec-path') : $('source')).focus({preventScroll:true});
};
$('open-confirm-plan').onclick = () => {
  const full = $('full-proposal'); if (!full || state.confirmedApprovalHash !== state.chat?.approval_hash) return;
  full.open = true; full.scrollIntoView({block:'start'}); full.querySelector('summary').focus({preventScroll:true});
};
$('chat-permission').onchange = renderAvailability;
$('chat-planning-permission').onchange = renderAvailability;
$('chat-prepare-placement').onclick = () => preparePlacement(false);
$('chat-placement-retry').onclick = () => preparePlacement(true);
$('node-enroll').onclick = enrollNode;
$('node-config-copy').onclick = copyNodeConfiguration;
$('node-config-download').onclick = downloadNodeConfiguration;
for (const id of ['node-name','node-gateway-url','node-gateway-host']) $(id).addEventListener('input',renderMachineAvailability);
$('chat-confirm').onsubmit = startChat;
$('cancel-chat-start').onclick = () => { $('chat-confirm').hidden = true; $('chat-permission').checked = false; $('chat-planning-permission').checked = false; state.confirmedApprovalHash = null; $('review-plan').focus(); };
$('linked-mission').onclick = () => { if (state.chat?.mission_id) selectMission(state.chat.mission_id); };
$('mission-inbox-refresh').onclick = readSelected;
$('mission-inbox-retry').onclick = () => sendMissionMessage(true);
$('back-to-chat').onclick = () => { const linked = state.chats.find(chat => chat.mission_id === state.id); if (linked) selectChat(linked.id); };
$('mission-start').onclick = () => {
  if (!missionControlAllowed('start')) return;
  confirmationContext($('mission-confirm-context'),missionMetadata().source,'',checkNamesForMission());
  const linked = missionChatView(state.id);
  if (linked.linked && planningAcknowledged(linked.chat)) $('mission-confirm-context').append(
    node('dt','原确认方案'),node('dd',clean(linked.chat.placement_preparation.approval_hash)));
  $('mission-confirm').hidden = false; $('mission-permission').checked = false; renderControlAvailability(); $('mission-permission').focus();
};
$('mission-permission').onchange = renderControlAvailability;
$('mission-confirm').onsubmit = event => { event.preventDefault(); return control('start'); };
$('cancel-mission-start').onclick = () => { $('mission-confirm').hidden = true; $('mission-permission').checked = false; $('mission-start').focus(); };
$('mission-pause').onclick = () => control('pause'); $('mission-resume').onclick = () => control('resume');
$('mission-stop').onclick = () => { if (missionControlAllowed('stop')) { $('stop-confirm').hidden = false; $('confirm-stop').focus(); } };
$('confirm-stop').onclick = () => control('stop');
$('cancel-stop').onclick = () => { $('stop-confirm').hidden = true; $('mission-stop').focus(); };
for (const id of ['load-retry','mission-refresh','uncertain-refresh']) $(id).onclick = readSelected;
$('inventory-retry').onclick = inventory;
$('reconnect').onclick = async () => { await inventory(); await readSelected(); };
$('ack-create').onclick = () => { clearPending('create'); showGlobal(''); renderAvailability(); };
$('uncertain-ack').onclick = () => {
  if (state.chat?.status !== 'IDLE' || !state.connected || !['message','context','attach'].includes(state.pending.get(pendingKey())?.type)) return;
  clearPending(pendingKey()); state.chatNotice = '已解除提交锁定。原请求不会重新发送；你可以继续新的讨论。'; render(); $('composer-input').focus();
};
$('jump-latest').onclick = () => { $('scroll-area').scrollTop = $('scroll-area').scrollHeight; $('jump-latest').hidden = true; };
$('scroll-area').addEventListener('scroll',() => {
  if ($('scroll-area').scrollHeight - $('scroll-area').scrollTop - $('scroll-area').clientHeight < 60) $('jump-latest').hidden = true;
});
document.addEventListener('keydown',event => {
  if (!state.drawer) return;
  if (event.key === 'Escape') { event.preventDefault(); closeDrawer(); return; }
  if (event.key !== 'Tab') return;
  const focusable = [...drawerElement().querySelectorAll('button:not([disabled]),a,input:not([disabled]),select:not([disabled]),textarea:not([disabled]),summary,[tabindex="0"]')]
    .filter(item => item.getClientRects().length && !item.closest('[hidden]'));
  if (!focusable.length) { event.preventDefault(); return; }
  const first = focusable[0], last = focusable.at(-1);
  if (event.shiftKey && (document.activeElement === first || !drawerElement().contains(document.activeElement))) { event.preventDefault(); last.focus(); }
  else if (!event.shiftKey && (document.activeElement === last || !drawerElement().contains(document.activeElement))) { event.preventDefault(); first.focus(); }
});
window.addEventListener('resize',() => { resizeComposer(); if (state.drawer === 'sidebar' && window.innerWidth > 700) closeDrawer(); });
window.addEventListener('online',() => { inventory().then(readSelected); });
window.addEventListener('offline',() => networkFailure('浏览器当前离线。'));
let polling = false;
async function poll() {
  if (polling) return; polling = true;
  try {
    if (!document.hidden && !state.busy) {
      if (Date.now() - state.inventoryAt > 15000) await inventory();
      await readSelected();
    }
  } finally {
    polling = false;
    setTimeout(poll,state.chat?.status === 'RUNNING' || state.kind === 'mission' || state.pending.has(pendingKey()) ? 1800 : 5000);
  }
}
document.addEventListener('visibilitychange',() => { if (!document.hidden && !state.busy) readSelected(); });
render(); resizeComposer();
if (storageIssue) showGlobal(storageIssue);
if (state.pending.has('create')) showGlobal('上次新对话的创建结果待确认。请先核对列表；不会自动创建第二次。',true);
inventory().then(async () => {
  if (state.epoch === 0 && state.kind === 'welcome') await restoreSelectedView();
  renderAvailability(); poll();
});
</script>
</body>
</html>'''
