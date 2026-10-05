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
        <section class="notice" id="chat-note" role="status" hidden><p id="chat-note-text" class="prose"></p><button class="text-button" id="context-action">设置工程与验收</button><button class="text-button" id="uncertain-refresh" hidden>查询最新记录</button><button class="text-button" id="uncertain-ack" hidden>已核对记录，继续讨论</button></section>
        <article class="proposal" id="proposal" aria-label="待确认方案草案" hidden><div class="draft-label">方案草案 · 尚未执行或验收</div><div id="proposal-body"></div></article>
        <section class="proposal-actions" id="proposal-actions" hidden><p class="small muted" id="readiness-note"></p><button class="primary" id="review-plan" aria-controls="preflight" aria-expanded="false">检查并准备开工</button>
        <section class="preflight" id="preflight" aria-labelledby="preflight-title" hidden>
          <h3 id="preflight-title" tabindex="-1">开工准备清单</h3>
          <p class="small" id="preflight-summary"></p>
          <ul id="preflight-requirements"></ul>
          <p class="small muted" id="preflight-note"></p>
          <details id="acceptance-help"><summary>文字验收已经聊好了，为什么还要准备？</summary><p>文字验收说明“做成什么样”；固定检查说明“如何验证通过或失败”。依据上方逐项验收编写校验脚本，把检查、通过/失败条件和执行范围写入工程验收文件，经你审阅后绑定。</p><p>这是工程准备步骤，不是让你重新讲一遍需求。当前聊天尚未接入自动生成这些文件的流程；如果指标还写着“约定阈值”，需先确认具体数值。不要复用其他无关工程的检查来凑开工条件。</p><p>绑定新工程或验收文件会保留聊天记录、撤下旧方案；随后请 Opus 基于新上下文重新核对方案。</p></details>
          <button class="secondary" id="preflight-settings" type="button">填写工程与验收</button>
        </section><button class="text-button" id="linked-mission" hidden>查看任务进度 →</button>
          <form class="confirmation" id="chat-confirm" hidden><h3>这次开工的范围</h3><dl id="chat-confirm-context"></dl><button type="button" class="text-button small" id="open-confirm-plan" aria-controls="full-proposal">查看本次确认的完整方案与验收</button><label class="permission"><input type="checkbox" id="chat-permission"><span>我允许这项任务在本机执行<small>本地工作进程将使用当前用户的访问权限，读取或修改工程、运行命令，并可能产生模型调用费用。</small></span></label><p class="small muted">方案仅是草案；最终结果以固定验收、独立审查与集成证据为准。</p><div class="flex wrap"><button class="primary" id="chat-start" type="submit" disabled>确认方案并开工</button><button class="text-button" id="cancel-chat-start" type="button">再想一想</button></div></form>
        </section>
      </div>
      <section id="mission-view" hidden aria-label="任务进度"><div class="flex wrap"><span class="mission-kicker">执行记录</span><button class="text-button small" id="back-to-chat" hidden>← 返回方案对话</button></div><h1 class="mission-title" id="mission-title"></h1><div class="mission-report" role="status"><h2 id="mission-status"></h2><p id="mission-reason" class="prose"></p><p id="acceptance-status"></p></div><div class="mission-toolbar" aria-label="任务控制"><button class="primary" id="mission-start">启动任务</button><button class="secondary" id="mission-pause">暂停派发</button><button class="secondary" id="mission-resume">恢复派发</button><button class="secondary danger-button" id="mission-stop">停止任务</button><button class="text-button" id="mission-refresh">刷新进度</button></div><p class="small muted" id="control-note" role="status"></p>
        <form id="mission-confirm" class="confirmation" hidden><h3>确认启动这项任务</h3><dl id="mission-confirm-context"></dl><label class="permission"><input type="checkbox" id="mission-permission"><span>我允许这项任务在本机执行<small>使用当前用户的访问权限，读取或修改工程、运行命令，并可能产生模型调用费用。</small></span></label><div class="flex wrap"><button class="primary" type="submit" id="mission-start-confirm" disabled>允许本地执行并启动</button><button class="text-button" type="button" id="cancel-mission-start">取消</button></div></form>
        <div id="stop-confirm" class="stop-note" hidden><p>停止是协作式请求。正在执行的调用可能仍在收尾；停止后不会自动重新开工。</p><div class="flex"><button class="secondary danger-button" id="confirm-stop">确认停止</button><button class="text-button" id="cancel-stop">取消</button></div></div>
        <section class="mission-section"><h3>工作拆解</h3><div id="task-list"></div></section><section class="mission-section"><h3>诊断、验收与集成</h3><div id="progress-thread"></div></section><section class="mission-section" id="event-section" hidden><h3>最近动态</h3><div id="event-thread"></div></section><button class="text-button small" id="mission-debug">查看原始证据与控制记录 →</button>
      </section>
    </div>
  </div>
  <button class="jump-latest" id="jump-latest" hidden>↓ 最新消息</button>
  <div class="composer-wrap" id="composer-wrap"><form class="composer" id="composer-form"><label class="sr-only" for="composer-input">你想一起做什么？</label><textarea id="composer-input" rows="2" placeholder="你想一起做什么？" autocomplete="off" aria-describedby="composer-help"></textarea><div class="composer-footer"><button class="composer-context" id="composer-settings" type="button">＋ 设置工程与验收</button><button class="send" id="send" type="submit" aria-label="发送消息" disabled>↑</button></div></form><div class="composer-hint" id="composer-help"><span id="model-label">先讨论，确认后才执行</span><span>Enter 发送 · Shift + Enter 换行</span></div></div>
</main>
</div>
<button class="backdrop" id="backdrop" aria-label="关闭抽屉" tabindex="-1" hidden></button>
<aside class="drawer" id="settings" role="dialog" aria-modal="true" aria-labelledby="settings-title" hidden><header class="drawer-header"><h2 id="settings-title">工程与验收</h2><button class="icon-button" id="close-settings" aria-label="关闭工程设置">×</button></header><div class="drawer-body"><p class="drawer-intro" id="settings-intro">先聊想法也可以。开工前，再绑定工程和已经批准的验收文件。</p><section id="reuse-project"><label class="field" for="existing-project">选择已有工程<select id="existing-project"><option value="">选择一个工程与验收方案…</option></select><small>按任务目标选择已批准的工程。不复用旧结果，也不会启动已有任务。</small></label><button class="primary" id="attach-mission" disabled>复用工程与验收</button><p class="small muted" id="attach-state" role="status"></p></section><details class="settings-section" id="manual-context"><summary>手动填写工程路径</summary><form id="context-form"><label class="field" for="source">工程目录<input id="source" type="text" placeholder="/Users/you/projects/my-project" autocomplete="off" spellcheck="false"><small>只绑定本机现存目录；输入路径不会创建目录。新工程先创建目录，再绑定。</small></label><label class="field" for="spec-path">验收文件<input id="spec-path" type="text" placeholder="/Users/you/specs/approved.json" autocomplete="off" spellcheck="false"><small>工程准备阶段产出的已批准验收文件（spec）的绝对路径。聊天中的文字验收不等于固定检查，尚未自动生成此文件。</small></label><div class="form-actions"><button class="primary" type="submit" id="save-context">保存设置</button><span class="small muted" id="context-save-state" role="status"></span></div><p class="small error prose" id="context-error" role="alert" hidden></p></form></details><details class="settings-section"><summary>已绑定的验收条件</summary><div id="context-checks"><p class="small muted">尚未绑定验收文件。</p></div></details><details class="settings-section"><summary>模型与执行说明</summary><div class="stack small muted"><p id="settings-model">尚无运行模型记录。</p><p>默认请求模型：负责人、独立审查使用 claude-opus-5-5；实施使用 gpt-6.1-sol。实际模型以运行回执为准。</p><p>总预算：Unlimited（默认不设总量上限）</p><p>已绑定任务的实际预算以核心记录为准；单次调用超时、并行限制与人工停止仍然生效。</p><p>对话与方案不会派发工作。开工时单独确认本地执行许可。</p><p>收到控制请求、模型返回或单项检查通过，都不等于整项任务已验收。</p><button class="text-button" id="settings-debug" type="button">打开诊断信息</button><a href="/console">旧版开发者控制台 ↗</a></div></details></div></aside>
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
  kind: 'welcome', id: '', epoch: 0, version: 0, chat: null, mission: null,
  chats: [], missions: [], issues: [], chatIssues: [], inventoryLoaded: false, inventoryError: '',
  loading: false, loadError: '', connected: false, networkError: '', lastRead: null,
  busy: null, cursor: 0, events: [], traces: [], drafts: new Map(), pending: new Map(),
  signatures: new Map(), drawer: null, returnFocus: null, contextDirty: false,
  contextOwner: '', contextValues: {source: '', spec_path: ''}, contextEpoch: 0,
  controlNote: '', chatNotice: '', forceScroll: false, composing: false,
  confirmFingerprint: '', confirmedApprovalHash: null, missionConfirmFingerprint: '', inventoryAt: 0
};
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
  const text = typeof value === 'string' ? value : JSON.stringify(value, null, 2);
  return token ? (text || '').split(token).join('[已隐藏凭据]') : (text || '');
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
async function api(path, body) {
  const post = body !== undefined;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), post ? 25000 : 14000);
  const started = Date.now();
  let status = 0;
  try {
    const response = await fetch(path, {
      method: post ? 'POST' : 'GET', cache: 'no-store', credentials: 'same-origin',
      signal: controller.signal,
      headers: {Authorization: 'Bearer ' + token, ...(post ? {'Content-Type': 'application/json'} : {})},
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
  PLANNING:'正在梳理实施方案', EXECUTING:'正在实施', VERIFYING:'正在验收', REVIEWING:'正在独立审查',
  INTEGRATING:'正在集成验证', WAITING_LEAD:'等待负责人继续分析', NEEDS_OPERATOR:'需要你确认下一步',
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
  inventoryPromise = (async () => {
    const results = await Promise.allSettled([api('/api/chats'), api('/api/missions')]);
    const errors = [];
    if (results[0].status === 'fulfilled' && Array.isArray(results[0].value.chats)) {
      state.chats = results[0].value.chats; state.chatIssues = array(results[0].value.issues);
      if (state.chatIssues.length) errors.push('有 ' + state.chatIssues.length + ' 段对话记录不完整，其他对话可继续使用');
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
function saveDraft() { state.drafts.set(state.kind === 'welcome' ? 'welcome' : state.id, $('composer-input').value); }
function resizeComposer() {
  const input = $('composer-input'); input.style.height = 'auto';
  input.style.height = Math.min(180, Math.max(48, input.scrollHeight)) + 'px';
}
function switchView(kind, id) {
  saveDraft(); closeDrawer(false); state.kind = kind; state.id = id; state.epoch++; state.version++;
  state.chat = null; state.mission = null; state.loadError = ''; state.loading = true;
  state.cursor = 0; state.events = []; state.controlNote = ''; state.chatNotice = '';
  state.contextOwner = ''; state.contextDirty = false; state.contextEpoch++;
  state.confirmFingerprint = ''; state.confirmedApprovalHash = null; state.missionConfirmFingerprint = '';
  $('preflight').hidden = true; $('review-plan').setAttribute('aria-expanded','false');
  $('chat-confirm').hidden = true; $('chat-permission').checked = false;
  $('mission-confirm').hidden = true; $('mission-permission').checked = false; $('stop-confirm').hidden = true;
  $('composer-input').value = state.drafts.get(id) || ''; resizeComposer();
  state.forceScroll = kind === 'chat'; render(); $('scroll-area').scrollTop = 0;
}
async function selectChat(id) { switchView('chat', id); await readSelected(); }
async function selectMission(id) { switchView('mission', id); await readSelected(); }
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
  try {
    if (kind === 'chat') {
      const chat = validateChat(await api('/api/chat?chat_id=' + encodeURIComponent(id)), id);
      if (!current()) return;
      state.loading = false; state.loadError = ''; networkSuccess(); applyChat(chat);
    } else {
      const data = await api('/api/snapshot?mission_id=' + encodeURIComponent(id));
      if (!data || !data.snapshot || typeof data.snapshot !== 'object' || !data.controller) throw new RequestError('任务快照格式不完整，请重新读取。');
      if (!current()) return;
      state.mission = data; state.loading = false; state.loadError = ''; reconcileControl(data); networkSuccess(); render(); syncSettings(false);
      const batch = await api('/api/events?mission_id=' + encodeURIComponent(id) + '&cursor=' + encodeURIComponent(state.cursor));
      if (!current()) return;
      if (!Array.isArray(batch.events) || !Number.isInteger(batch.cursor) || batch.cursor < state.cursor) throw new RequestError('任务事件游标异常，请重新读取。');
      const seen = new Set(state.events.map(event => event.seq));
      state.events.push(...batch.events.filter(event => !seen.has(event.seq)));
      state.events = state.events.slice(-160); state.cursor = batch.cursor; renderEvents();
    }
  } catch (error) {
    if (!current()) return;
    state.loading = false; state.loadError = clean(error.message); networkFailure(error.message); render();
  }
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
function canSend() {
  return !state.busy && !state.loading && !state.loadError && !state.pending.has(pendingKey()) &&
    !state.pending.has('create') && state.connected && state.kind !== 'mission' &&
    (state.kind === 'welcome' || state.chat?.status === 'IDLE' || state.chat?.status === 'ERROR') &&
    !state.chat?.mission_id;
}
function renderAvailability() {
  $('send').disabled = !canSend() || !$('composer-input').value.trim();
  $('composer-input').readOnly = !!state.busy || !!state.chat?.mission_id || state.chat?.status === 'UNKNOWN';
  $('composer-input').placeholder = state.chat?.mission_id ? '这段方案已经开工。新建对话，讨论下一个想法。' : '你想一起做什么？';
  $('save-context').disabled = state.kind === 'mission' || !!state.busy || state.loading ||
    state.pending.has(pendingKey()) || state.pending.has('create') || !state.connected ||
    (state.chat && (state.chat.status !== 'IDLE' && state.chat.status !== 'ERROR' || !!state.chat.mission_id));
  $('attach-mission').disabled = $('save-context').disabled || !$('existing-project').value;
  $('existing-project').disabled = $('save-context').disabled;
  $('review-plan').disabled = !canPrepare();
  $('chat-start').disabled = !canChatStart() || !$('chat-permission').checked;
  $('new-chat').disabled = !!state.busy || state.pending.has('create');
  renderControlAvailability();
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
    row.append(node('div', role === 'user' ? '你' : '技术负责人', 'message-author'), node('div', message.text || '', 'message-text prose'));
    return row;
  }));
  if (changed) { state.forceScroll = state.forceScroll || wasAtBottom; scrollLatest(); }
  const pending = state.pending.get(pendingKey());
  $('waiting').hidden = chat.status !== 'RUNNING' && !(state.busy?.type === 'message' && state.busy.id === chat.id);
  $('waiting-text').textContent = state.busy?.type === 'message' ? '正在发送这条消息…' : '正在思考，回复会出现在这里。无需重复发送。';
  let note = state.chatNotice || missingContextMessage(chat);
  if (pending) note = '这次' + ({message:'消息',start:'开工',context:'设置保存',attach:'工程复用'}[pending.type] || '操作') + '的结果尚未确认。已暂停新的提交；请查询记录，系统不会自动重发。';
  else if (chat.status === 'UNKNOWN') note = '上一次调用的结果仍待确认。先查询最新记录，不重复发起调用。';
  else if (chat.status === 'ERROR') note = '这次对话遇到了问题。' + (chat.error ? ' ' + clean(typeof chat.error === 'string' ? chat.error : chat.error.message || '') : '') + ' 你可以先核对记录，再继续讨论。';
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
    $('chat-confirm').hidden = true; $('chat-permission').checked = false; state.confirmedApprovalHash = null;
    if (hadConfirmation) say('开工范围已变化，请重新审阅并确认。');
  }
  state.confirmFingerprint = fingerprint;
  if (!proposal || chat.mission_id) { $('preflight').hidden = true; $('review-plan').setAttribute('aria-expanded','false'); }
  else if (!$('preflight').hidden) renderPreflight(chat);
  if (!chatReady()) { $('chat-confirm').hidden = true; $('chat-permission').checked = false; state.confirmedApprovalHash = null; }
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
  $('acceptance-help').hidden = !missing.some(item => item.id === 'acceptance');
}
function reviewPlan() {
  if (!canPrepare()) return;
  renderPreflight(state.chat); $('preflight').hidden = false; $('review-plan').setAttribute('aria-expanded','true');
  // Inspection and preparation are read-only; only a ready, connected draft
  // may show the separate execution-permission confirmation.
  if (!canChatStart()) {
    $('chat-confirm').hidden = true; $('chat-permission').checked = false; state.confirmedApprovalHash = null;
    renderAvailability(); $('preflight').scrollIntoView({block:'nearest'}); $('preflight-title').focus({preventScroll:true}); return;
  }
  confirmationContext($('chat-confirm-context'),state.chat.source,state.chat.spec_path,checksForChat(state.chat).map(check => check.id || check.check).filter(Boolean));
  state.confirmedApprovalHash = state.chat.approval_hash;
  $('chat-confirm').hidden = false; $('chat-permission').checked = false; renderAvailability(); $('chat-permission').focus();
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
async function sendMessage() {
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
      state.drafts.set(id,message); switchView('chat',id); state.loading = false; applyChat(created);
    }
    const ownerEpoch = state.epoch;
    const before = array(state.chat?.messages).map(item => item.id).filter(Boolean);
    $('composer-input').value = ''; state.drafts.set(id,''); resizeComposer(); state.forceScroll = true;
    state.chatNotice = ''; render(); sent = true;
    try {
      const chat = validateChat(await api('/api/chat/message',{chat_id:id,message,request_id:uuid}),id,true);
      upsertChat(chat);
      if (state.kind === 'chat' && state.id === id && state.epoch === ownerEpoch) applyChat(chat);
    } catch (error) {
      markUncertain('chat:' + id,{type:'message',request_id:uuid,before},error);
      if (!error.uncertain) {
        state.drafts.set(id,message);
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
function missionMetadata() { return state.missions.find(item => item.id === state.id) || {}; }
function missionControlAllowed(action) {
  if (state.kind !== 'mission' || !state.mission || state.loading || state.busy || !state.connected || state.loadError) return false;
  if (state.pending.has(pendingKey()) && action !== 'stop') return false;
  const snapshot = state.mission.snapshot, controller = state.mission.controller;
  if (snapshot.stopped || controller.stop_requested || snapshot.all_verified === true) return false;
  if (action === 'start') return !controller.running;
  if (action === 'pause') return controller.running && !snapshot.paused;
  if (action === 'resume') return !!snapshot.paused;
  return action === 'stop';
}
function renderControlAvailability() {
  for (const action of ['start','pause','resume','stop']) $('mission-' + action).disabled = !missionControlAllowed(action);
  $('mission-start-confirm').disabled = !missionControlAllowed('start') || !$('mission-permission').checked;
  $('confirm-stop').disabled = !missionControlAllowed('stop');
}
function reconcileControl(data) {
  const key = 'mission:' + state.id, pending = state.pending.get(key); if (!pending) return;
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
function renderMission() {
  const data = state.mission; if (!data) return;
  const snapshot = data.snapshot, controller = data.controller, meta = missionMetadata();
  $('view-title').textContent = '任务进度'; $('view-subtitle').textContent = state.id;
  $('mission-title').textContent = snapshot.objective || meta.objective || '这次任务';
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
  paint('task-list', tasks.map(task => ({...Object.fromEntries(['id','title','objective','acceptance','check','state','status','verdict','stale','active','attempts','depends_on'].map(key => [key,task[key]])),checks:verificationChecks(task.verification).map(checkResult),review:verificationReview(task.verification)})), () => {
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
      if (array(task.depends_on).length) detail.append(node('p','依赖：' + task.depends_on.join('、'),'prose'));
      if (task.attempts !== undefined) detail.append(node('p','保留的尝试：' + task.attempts));
      detailLines(detail,verificationChecks(task.verification));
      const review = verificationReview(task.verification);
      if (review.verdict) detail.append(node('p','独立审查：' + reviewStatus(review.verdict) + ' · ' + array(review.reasons).join('；'),'prose'));
      row.append(detail); return row;
    });
  });
  renderProgress(snapshot,tasks); renderEvents();
  const fingerprint = JSON.stringify([meta.source,checkNamesForMission()]);
  if (state.missionConfirmFingerprint && state.missionConfirmFingerprint !== fingerprint) {
    $('mission-confirm').hidden = true; $('mission-permission').checked = false;
  }
  state.missionConfirmFingerprint = fingerprint;
  if (!missionControlAllowed('start') && !state.busy) { $('mission-confirm').hidden = true; $('mission-permission').checked = false; }
}
function threadEntry(title, lines) {
  const entry = node('article',undefined,'thread-entry'); entry.append(node('h4',title));
  for (const line of lines) if (line) entry.append(node('p',line,'prose'));
  return entry;
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
  $('composer-wrap').hidden = isMission;
  $('load-state').hidden = !state.loading;
  $('load-error').hidden = !state.loadError;
  $('load-error-text').textContent = state.loadError + ' 已保留本页输入，重新读取不会再次提交。';
  if (isChat) renderChat();
  if (isMission) renderMission();
  renderConnection(); renderLists(); renderAvailability();
  if (state.drawer === 'debug') renderDebug();
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
      saveDraft(); const draft = state.drafts.get('welcome') || '';
      state.kind = 'chat'; state.id = id; state.epoch++; state.chat = created;
      state.drafts.set(id,draft); state.contextOwner = 'chat:' + id; upsertChat(created);
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
      saveDraft(); const draft = state.drafts.get('welcome') || '';
      state.kind = 'chat'; state.id = id; state.epoch++; state.chat = created;
      state.drafts.set(id,draft); state.contextOwner = 'chat:' + id; upsertChat(created);
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
$('preflight-settings').onclick = () => {
  openDrawer('settings'); $('manual-context').open = true;
  (state.chat?.source ? $('spec-path') : $('source')).focus({preventScroll:true});
};
$('open-confirm-plan').onclick = () => {
  const full = $('full-proposal'); if (!full || state.confirmedApprovalHash !== state.chat?.approval_hash) return;
  full.open = true; full.scrollIntoView({block:'start'}); full.querySelector('summary').focus({preventScroll:true});
};
$('chat-permission').onchange = renderAvailability;
$('chat-confirm').onsubmit = startChat;
$('cancel-chat-start').onclick = () => { $('chat-confirm').hidden = true; $('chat-permission').checked = false; state.confirmedApprovalHash = null; $('review-plan').focus(); };
$('linked-mission').onclick = () => { if (state.chat?.mission_id) selectMission(state.chat.mission_id); };
$('back-to-chat').onclick = () => { const linked = state.chats.find(chat => chat.mission_id === state.id); if (linked) selectChat(linked.id); };
$('mission-start').onclick = () => {
  if (!missionControlAllowed('start')) return;
  confirmationContext($('mission-confirm-context'),missionMetadata().source,'',checkNamesForMission());
  $('mission-confirm').hidden = false; $('mission-permission').checked = false; renderControlAvailability(); $('mission-permission').focus();
};
$('mission-permission').onchange = renderControlAvailability;
$('mission-confirm').onsubmit = event => { event.preventDefault(); control('start'); };
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
inventory().then(() => { renderAvailability(); poll(); });
</script>
</body>
</html>'''
