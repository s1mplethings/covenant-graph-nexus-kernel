import argparse
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

# Import milestone modules. Each module exposes handle(data_dir, request).
try:
    from milestones.milestone_20f2614f6ae8403d4a4e.api import handle as m1_handle
except ImportError:
    m1_handle = None

try:
    from milestones.milestone_4e7c26281cf61a85851e.api import handle as m2_handle
except ImportError:
    m2_handle = None

try:
    from milestones.milestone_1369a82cde04a7e5887d.api import handle as m3_handle
except ImportError:
    m3_handle = None

try:
    from milestones.milestone_90b8868c7203e2958397.api import handle as m4_handle
except ImportError:
    m4_handle = None

try:
    from milestones.milestone_9165a990eed5b9c8801e.api import handle as m5_handle
except ImportError:
    m5_handle = None

try:
    from milestones.milestone_33270fed0c9054f5ae04.api import handle as m6_handle
except ImportError:
    m6_handle = None

try:
    from promotion_publish import handle as m7_handle
except ImportError:
    m7_handle = None

try:
    from milestones.milestone_989800776c3d6229e431.api import handle as m8_handle
except ImportError:
    m8_handle = None

try:
    from milestones.milestone_c511a8ebd29978f5ba97.api import handle as m9_handle
except ImportError:
    m9_handle = None

try:
    from milestones.milestone_af427946c6dea418047a.api import handle as m10_handle
except ImportError:
    m10_handle = None

try:
    from milestones.milestone_dbb8341c8910593063a8.api import handle as m11_handle
except ImportError:
    m11_handle = None

MILESTONE_ID = 'M12'

HANDLERS = {
    'M1': m1_handle,
    'M2': m2_handle,
    'M3': m3_handle,
    'M4': m4_handle,
    'M5': m5_handle,
    'M6': m6_handle,
    'M7': m7_handle,
    'M8': m8_handle,
    'M9': m9_handle,
    'M10': m10_handle,
    'M11': m11_handle,
}

OP_PREFIX_MAP = {
    'project.': 'M1',
    'evidence.': 'M2',
    'signal.': 'M2',
    'claim.': 'M3',
    'campaign.': 'M4',
    'content.': 'M5',
    'approval.': 'M6',
    'publish.': 'M7',
    'schedule.': 'M11',
    'analytics.': 'M11',
    'media.': 'M11',
}


def _infer_milestone(request):
    milestone = request.get('milestone')
    if isinstance(milestone, str) and milestone:
        return milestone
    op = request.get('op')
    if isinstance(op, str) and op:
        for prefix, mid in OP_PREFIX_MAP.items():
            if op.startswith(prefix):
                return mid
    return None


def handle(data_dir, request):
    if not isinstance(data_dir, str) or not data_dir:
        raise ValueError('data_dir must be a non-empty string')
    if not isinstance(request, dict):
        raise ValueError('request must be a dict')

    op = request.get('op')
    if not isinstance(op, str) or not op:
        raise ValueError("Missing 'op' field")

    if op == 'product.status':
        missing = [k for k, v in HANDLERS.items() if v is None]
        if missing:
            raise ValueError('Missing modules: %s' % ', '.join(missing))
        return {
            'status': 'ready',
            'milestones': ['M1', 'M2', 'M3', 'M4', 'M5', 'M6', 'M7', 'M8', 'M9', 'M10', 'M11', 'M12'],
        }

    milestone = _infer_milestone(request)
    if not milestone:
        raise ValueError("Missing 'milestone' field or unable to infer from op")

    handler = HANDLERS.get(milestone)
    if handler is None:
        raise ValueError('Unknown milestone: %s' % milestone)

    return handler(data_dir, request)


INDEX_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Promotion Studio</title>
<style>
  body { font-family: sans-serif; margin: 1rem; }
  section { border: 1px solid #ccc; padding: 0.75rem; margin-bottom: 1rem; }
  label { display: block; margin-top: 0.5rem; }
  input, textarea, select { width: 100%; max-width: 32rem; }
  button { margin-top: 0.5rem; margin-right: 0.5rem; }
  #alert { color: #b00020; }
  #status { color: #0b6b0b; }
  ul { list-style: none; padding-left: 0; }
  nav { margin-bottom: 1rem; }
  nav button { margin-right: 0.5rem; }
  .context-name { font-weight: bold; display: block; margin-top: 0.25rem; }
  .view { display: none; }
  .view.active { display: block; }
  button:disabled { opacity: 0.5; cursor: not-allowed; }
  .media-preview { max-width: 20rem; max-height: 20rem; display: block; margin-top: 0.5rem; }
  .media-item { border: 1px solid #ddd; padding: 0.5rem; margin-bottom: 0.5rem; }
  .media-error { color: #b00020; }
</style>
</head>
<body>
<h1>Promotion Studio</h1>
<nav id="main-nav" aria-label="Primary">
  <button id="nav-projects" type="button" data-view="projects-view">Projects</button>
  <button id="nav-signals" type="button" data-view="signals-view">Signals</button>
  <button id="nav-campaigns" type="button" data-view="campaigns-view">Campaigns</button>
  <button id="nav-content" type="button" data-view="content-view">Content</button>
  <button id="nav-schedule" type="button" data-view="schedule-view">Schedule/Publish</button>
  <button id="nav-receipts-analytics" type="button" data-view="receipts-analytics-view">Receipts/Analytics</button>
</nav>
<div id="alert" role="alert"></div>
<div id="status" role="status"></div>

<section id="projects-view" class="view active">
  <h2>Projects</h2>
  <label for="project-name">Project name</label>
  <input id="project-name" type="text">
  <button id="create-project" type="button">Create project</button>
  <label for="project-select">Select project</label>
  <select id="project-select"></select>
  <span id="current-project-name" class="context-name"></span>
</section>

<section id="signals-view" class="view">
  <h2>Signals</h2>
  <label for="signal-text">Signal text</label>
  <input id="signal-text" type="text">
  <button id="create-signal" type="button">Create signal</button>
  <ul id="signal-list"></ul>
</section>

<section id="campaigns-view" class="view">
  <h2>Campaigns</h2>
  <label for="campaign-name">Campaign name</label>
  <input id="campaign-name" type="text">
  <label for="campaign-audience">Audience</label>
  <input id="campaign-audience" type="text">
  <label for="campaign-channels">Channels</label>
  <input id="campaign-channels" type="text" placeholder="comma-separated">
  <button id="create-campaign" type="button">Create campaign</button>
  <label for="campaign-select">Select campaign</label>
  <select id="campaign-select"></select>
  <span id="current-campaign-name" class="context-name"></span>
</section>

<section id="content-view" class="view">
  <h2>Content</h2>
  <label for="content-text">Content text</label>
  <textarea id="content-text" rows="4"></textarea>
  <label for="content-channel">Channel</label>
  <select id="content-channel"></select>
  <label for="content-claims">Claims</label>
  <select id="content-claims"></select>
  <label for="content-media">Media</label>
  <select id="content-media"></select>
  <button id="save-content" type="button">Save content</button>
  <button id="review-action" type="button">Review</button>
  <button id="approve-action" type="button">Approve</button>
  <label for="content-select">Select content</label>
  <select id="content-select"></select>
  <div id="content-media-preview"></div>
  <label for="media-upload">Upload media</label>
  <input id="media-upload" type="file">
  <button id="upload-media-btn" type="button">Import Media</button>
</section>

<section id="schedule-view" class="view">
  <h2>Schedule / Publish</h2>
  <label for="platform-url">Platform URL</label>
  <input id="platform-url" type="text">
  <label for="when-input">When</label>
  <input id="when-input" type="text" placeholder="2023-10-27T10:00:00Z">
  <button id="publish-action" type="button">Publish</button>
  <button id="schedule-action" type="button">Schedule</button>
  <button id="cancel-action" type="button">Cancel</button>
  <button id="reschedule-action" type="button">Reschedule</button>
  <button id="fetch-analytics" type="button">Fetch analytics</button>
  <ul id="schedule-list"></ul>
</section>

<section id="receipts-analytics-view" class="view">
  <h2>Receipts</h2>
  <button id="refresh-receipts" type="button">Refresh receipts</button>
  <ul id="receipt-list"></ul>
  <h2>Analytics</h2>
  <button id="refresh-analytics" type="button">Refresh analytics</button>
  <ul id="analytics-list"></ul>
</section>

<script>
(function () {
  'use strict';

  var state = {
    projectId: null,
    campaignId: null,
    contentId: null,
    scheduleId: null,
    projects: [],
    campaigns: [],
    claims: [],
    contents: [],
    media: [],
    receipts: [],
    schedules: [],
    contentStatus: null,
    approvalStatus: null,
    actionQueue: Promise.resolve()
  };

  function el(id) { return document.getElementById(id); }
  function setAlert(msg) { el('alert').textContent = msg || ''; }
  function setStatus(msg) { el('status').textContent = msg || ''; }

  function action(payload) {
    return fetch('/api/action', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    }).then(function (resp) {
      return resp.json().then(function (data) {
        if (!resp.ok) {
          var msg = (data && data.error) ? data.error : ('HTTP ' + resp.status);
          throw new Error(msg);
        }
        return data;
      });
    });
  }

  function enqueue(task) {
    state.actionQueue = state.actionQueue.then(task, task);
    return state.actionQueue;
  }

  function itemsOf(result) {
    if (!result) return [];
    if (Array.isArray(result)) return result;
    if (Array.isArray(result.items)) return result.items;
    if (Array.isArray(result.projects)) return result.projects;
    if (Array.isArray(result.campaigns)) return result.campaigns;
    if (Array.isArray(result.contents)) return result.contents;
    if (Array.isArray(result.media)) return result.media;
    if (Array.isArray(result.receipts)) return result.receipts;
    if (Array.isArray(result.schedules)) return result.schedules;
    if (Array.isArray(result.claims)) return result.claims;
    return [];
  }

  function fillSelect(select, items, idKey, labelKey) {
    if (!select) return;
    select.innerHTML = '';
    items.forEach(function (item) {
      var opt = document.createElement('option');
      opt.value = item[idKey];
      opt.textContent = item[labelKey] || item[idKey];
      select.appendChild(opt);
    });
  }

  function setContextName(id, text) {
    var node = el(id);
    if (node) node.textContent = text || '';
  }

  function showView(viewId) {
    var views = ['projects-view', 'signals-view', 'campaigns-view', 'content-view', 'schedule-view', 'receipts-analytics-view'];
    views.forEach(function (id) {
      var node = el(id);
      if (node) node.classList.remove('active');
    });
    var target = el(viewId);
    if (target) target.classList.add('active');
  }

  function updateReadiness() {
    var hasProject = !!state.projectId;
    var hasCampaign = !!state.campaignId;
    var hasContent = !!state.contentId;
    var isDraft = state.contentStatus === 'DRAFT';
    var isReviewed = state.approvalStatus === 'REVIEW';
    var isApproved = state.approvalStatus === 'APPROVED';

    if (el('create-campaign')) el('create-campaign').disabled = !hasProject;
    if (el('save-content')) el('save-content').disabled = !hasProject || !hasCampaign;
    if (el('review-action')) el('review-action').disabled = !hasContent || !isDraft;
    if (el('approve-action')) el('approve-action').disabled = !hasContent || !isReviewed;
    if (el('publish-action')) el('publish-action').disabled = !hasContent || !isApproved;
    if (el('schedule-action')) el('schedule-action').disabled = !hasContent || !isApproved;
  }

  function loadProjects() {
    return action({ milestone: 'M1', op: 'project.list' }).then(function (res) {
      var items = itemsOf(res);
      state.projects = items;
      fillSelect(el('project-select'), items, 'id', 'name');
      if (items.length) {
        var saved = localStorage.getItem('projectId');
        var match = items.filter(function (p) { return p.id === saved; })[0];
        state.projectId = match ? match.id : items[0].id;
        el('project-select').value = state.projectId;
        localStorage.setItem('projectId', state.projectId);
        var current = items.filter(function (p) { return p.id === state.projectId; })[0];
        setContextName('current-project-name', current ? current.name : '');
      } else {
        state.projectId = null;
        setContextName('current-project-name', '');
      }
      updateReadiness();
      return items;
    });
  }

  function loadCampaigns() {
    if (!state.projectId) {
      state.campaigns = [];
      fillSelect(el('campaign-select'), [], 'id', 'name');
      if (el('content-channel')) el('content-channel').innerHTML = '';
      state.campaignId = null;
      setContextName('current-campaign-name', '');
      updateReadiness();
      return Promise.resolve([]);
    }
    return action({ milestone: 'M4', op: 'campaign.list', project_id: state.projectId }).then(function (res) {
      var items = itemsOf(res);
      state.campaigns = items;
      fillSelect(el('campaign-select'), items, 'id', 'name');
      if (items.length) {
        var saved = localStorage.getItem('campaignId');
        var match = items.filter(function (c) { return c.id === saved; })[0];
        state.campaignId = match ? match.id : items[0].id;
        el('campaign-select').value = state.campaignId;
        localStorage.setItem('campaignId', state.campaignId);
        var current = items.filter(function (c) { return c.id === state.campaignId; })[0];
        setContextName('current-campaign-name', current ? current.name : '');
        var channels = (current && current.channels) || [];
        fillSelect(el('content-channel'), channels.map(function (c) { return { id: c, name: c }; }), 'id', 'name');
      } else {
        state.campaignId = null;
        setContextName('current-campaign-name', '');
        if (el('content-channel')) el('content-channel').innerHTML = '';
      }
      updateReadiness();
      return items;
    });
  }

  function loadClaims() {
    if (!state.projectId) {
      state.claims = [];
      fillSelect(el('content-claims'), [], 'id', 'text');
      return Promise.resolve([]);
    }
    return action({ milestone: 'M3', op: 'claim.list', project_id: state.projectId }).then(function (res) {
      var items = itemsOf(res);
      state.claims = items;
      fillSelect(el('content-claims'), items, 'id', 'text');
      return items;
    }).catch(function () {
      state.claims = [];
      fillSelect(el('content-claims'), [], 'id', 'text');
      return [];
    });
  }

  function loadMedia() {
    if (!state.projectId) {
      state.media = [];
      fillSelect(el('content-media'), [], 'id', 'filename');
      return Promise.resolve([]);
    }
    return action({ milestone: 'M11', op: 'media.list', project_id: state.projectId }).then(function (res) {
      var items = itemsOf(res);
      state.media = items;
      fillSelect(el('content-media'), items, 'id', 'filename');
      return items;
    }).catch(function () {
      state.media = [];
      fillSelect(el('content-media'), [], 'id', 'filename');
      return [];
    });
  }

  function mediaUrl(projectId, mediaId) {
    return '/media/' + encodeURIComponent(mediaId) + '?project_id=' + encodeURIComponent(projectId);
  }

  function renderContentMediaPreview(content) {
    var container = el('content-media-preview');
    if (!container) return;
    container.innerHTML = '';
    if (!content) return;
    var ids = content.media_ids || [];
    ids.forEach(function (mid) {
      var m = state.media.filter(function (x) { return x.id === mid; })[0];
      var wrap = document.createElement('div');
      wrap.className = 'media-item';
      if (!m || m.status !== 'VALID') {
        var broken = document.createElement('div');
        broken.className = 'media-error';
        broken.textContent = 'Media unavailable: ' + (m ? (m.filename || m.id) : mid);
        wrap.appendChild(broken);
        container.appendChild(wrap);
        return;
      }
      var media = document.createElement(m.kind === 'video' ? 'video' : 'img');
      media.className = 'media-preview';
      media.setAttribute('data-media-id', m.id);
      if (m.kind === 'video') media.setAttribute('controls', 'controls');
      media.src = mediaUrl(state.projectId, m.id);
      media.onerror = function () {
        var err = document.createElement('div');
        err.className = 'media-error';
        err.textContent = 'Failed to load media bytes for ' + (m.filename || m.id);
        wrap.appendChild(err);
      };
      wrap.appendChild(media);
      container.appendChild(wrap);
    });
  }

  function hydrateContentForm(content) {
    if (!content) return;
    if (el('content-text')) el('content-text').value = content.text || '';
    var channelSel = el('content-channel');
    if (channelSel) {
      var campaign = state.campaigns.filter(function (c) { return c.id === state.campaignId; })[0];
      var channels = (campaign && campaign.channels) || [];
      channelSel.innerHTML = '';
      channels.forEach(function (ch) {
        var opt = document.createElement('option');
        opt.value = ch;
        opt.textContent = ch;
        if (ch === content.channel) opt.selected = true;
        channelSel.appendChild(opt);
      });
    }
    var claimsSel = el('content-claims');
    if (claimsSel) {
      var claimIds = content.claim_ids || [];
      Array.prototype.forEach.call(claimsSel.options, function (opt) {
        opt.selected = claimIds.indexOf(opt.value) >= 0;
      });
    }
    var mediaSel = el('content-media');
    if (mediaSel) {
      var mediaIds = content.media_ids || [];
      Array.prototype.forEach.call(mediaSel.options, function (opt) {
        opt.selected = mediaIds.indexOf(opt.value) >= 0;
      });
    }
    renderContentMediaPreview(content);
  }

  function loadContents() {
    if (!state.projectId) {
      state.contents = [];
      fillSelect(el('content-select'), [], 'id', 'text');
      state.contentId = null;
      state.contentStatus = null;
      state.approvalStatus = null;
      renderContentMediaPreview(null);
      updateReadiness();
      return Promise.resolve([]);
    }
    return action({ milestone: 'M5', op: 'content.list', project_id: state.projectId }).then(function (res) {
      var items = itemsOf(res);
      state.contents = items;
      fillSelect(el('content-select'), items, 'id', 'text');
      if (items.length) {
        var saved = localStorage.getItem('contentId');
        var match = items.filter(function (c) { return c.id === saved; })[0];
        state.contentId = match ? match.id : items[0].id;
        el('content-select').value = state.contentId;
        localStorage.setItem('contentId', state.contentId);
        var current = items.filter(function (c) { return c.id === state.contentId; })[0];
        state.contentStatus = current ? (current.status || 'DRAFT') : 'DRAFT';
        hydrateContentForm(current);
        return projectApprovalStatus().then(function () {
          updateReadiness();
          return items;
        });
      } else {
        state.contentId = null;
        state.contentStatus = null;
        state.approvalStatus = null;
        renderContentMediaPreview(null);
      }
      updateReadiness();
      return items;
    });
  }

  function projectApprovalStatus() {
    if (!state.projectId || !state.contentId) {
      state.approvalStatus = null;
      return Promise.resolve(null);
    }
    return action({
      milestone: 'M6', op: 'approval.status',
      project_id: state.projectId, content_id: state.contentId
    }).then(function (res) {
      var status = null;
      if (res && typeof res === 'object') status = res.status || res.approval_status || null;
      state.approvalStatus = status;
      return status;
    }).catch(function () {
      state.approvalStatus = null;
      return null;
    });
  }

  function loadReceipts() {
    if (!state.projectId) {
      state.receipts = [];
      el('receipt-list').innerHTML = '';
      return Promise.resolve([]);
    }
    return action({ milestone: 'M7', op: 'publish.list', project_id: state.projectId }).then(function (res) {
      var items = itemsOf(res);
      state.receipts = items;
      var list = el('receipt-list');
      list.innerHTML = '';
      items.forEach(function (r) {
        var li = document.createElement('li');
        li.textContent = (r.id || '') + ' - ' + (r.status || '') + ' - remote_id: ' + (r.remote_id || 'pending');
        list.appendChild(li);
      });
      return items;
    }).catch(function () { return []; });
  }

  function loadSchedules() {
    if (!state.projectId) {
      state.schedules = [];
      if (el('schedule-list')) el('schedule-list').innerHTML = '';
      return Promise.resolve([]);
    }
    return action({ milestone: 'M11', op: 'schedule.list', project_id: state.projectId }).then(function (res) {
      var items = itemsOf(res);
      state.schedules = items;
      var list = el('schedule-list');
      if (list) {
        list.innerHTML = '';
        items.forEach(function (s) {
          var li = document.createElement('li');
          li.textContent = (s.id || '') + ' - ' + (s.status || '') + ' - when: ' + (s.when || '');
          list.appendChild(li);
        });
      }
      return items;
    }).catch(function () { return []; });
  }

  function loadAnalytics() {
    if (!state.projectId) {
      el('analytics-list').innerHTML = '';
      return Promise.resolve([]);
    }
    return action({ milestone: 'M11', op: 'analytics.list', project_id: state.projectId }).then(function (res) {
      var items = itemsOf(res);
      var list = el('analytics-list');
      list.innerHTML = '';
      items.forEach(function (a) {
        var li = document.createElement('li');
        li.textContent = JSON.stringify(a);
        list.appendChild(li);
      });
      return items;
    }).catch(function () {
      el('analytics-list').innerHTML = '';
      return [];
    });
  }

  function refreshAll() {
    return loadProjects()
      .then(loadCampaigns)
      .then(loadClaims)
      .then(loadMedia)
      .then(loadContents)
      .then(loadReceipts)
      .then(loadSchedules)
      .catch(function (e) { setAlert(e.message); });
  }

  function bind(id, handler) {
    var node = el(id);
    if (node) node.addEventListener('click', handler);
  }

  function init() {
    bind('create-project', function () {
      setAlert(''); setStatus('');
      var name = el('project-name').value;
      enqueue(function () {
        return action({ milestone: 'M1', op: 'project.create', name: name }).then(function (res) {
          setStatus('Created project: ' + (res.name || name));
          return refreshAll();
        });
      }).catch(function (e) { setAlert(e.message); });
    });

    el('project-select').addEventListener('change', function () {
      state.projectId = el('project-select').value;
      localStorage.setItem('projectId', state.projectId);
      var opt = el('project-select').options[el('project-select').selectedIndex];
      setContextName('current-project-name', opt ? opt.textContent : '');
      enqueue(function () {
        return loadCampaigns().then(loadClaims).then(loadMedia).then(loadContents).then(loadReceipts).then(loadSchedules);
      }).catch(function (e) { setAlert(e.message); });
    });

    bind('create-signal', function () {
      setAlert(''); setStatus('');
      var text = el('signal-text').value;
      enqueue(function () {
        return action({ milestone: 'M2', op: 'signal.create', project_id: state.projectId, text: text }).then(function () {
          setStatus('Signal created');
          return loadClaims();
        });
      }).catch(function (e) { setAlert(e.message); });
    });

    bind('create-campaign', function () {
      setAlert(''); setStatus('');
      var channels = el('campaign-channels').value.split(',').map(function (s) { return s.trim(); }).filter(Boolean);
      enqueue(function () {
        return action({
          milestone: 'M4', op: 'campaign.create', project_id: state.projectId,
          name: el('campaign-name').value, audience: el('campaign-audience').value, channels: channels
        }).then(function (res) {
          setStatus('Created campaign: ' + (res.name || el('campaign-name').value));
          return loadCampaigns();
        });
      }).catch(function (e) { setAlert(e.message); });
    });

    el('campaign-select').addEventListener('change', function () {
      state.campaignId = el('campaign-select').value;
      localStorage.setItem('campaignId', state.campaignId);
      var opt = el('campaign-select').options[el('campaign-select').selectedIndex];
      setContextName('current-campaign-name', opt ? opt.textContent : '');
      var current = state.campaigns.filter(function (c) { return c.id === state.campaignId; })[0];
      var channels = (current && current.channels) || [];
      fillSelect(el('content-channel'), channels.map(function (c) { return { id: c, name: c }; }), 'id', 'name');
      updateReadiness();
    });

    bind('save-content', function () {
      setAlert(''); setStatus('');
      var claimSel = el('content-claims');
      var claimIds = claimSel ? Array.prototype.filter.call(claimSel.options, function (o) { return o.selected; }).map(function (o) { return o.value; }) : [];
      var mediaSel = el('content-media');
      var mediaIds = mediaSel ? Array.prototype.filter.call(mediaSel.options, function (o) { return o.selected; }).map(function (o) { return o.value; }) : [];
      enqueue(function () {
        return action({
          milestone: 'M5', op: 'content.create', project_id: state.projectId,
          campaign_id: state.campaignId, text: el('content-text').value,
          channel: el('content-channel').value, claim_ids: claimIds, media_ids: mediaIds
        }).then(function (res) {
          setStatus('Saved content: ' + (res.id || ''));
          return loadContents();
        });
      }).catch(function (e) { setAlert(e.message); });
    });

    el('content-select').addEventListener('change', function () {
      state.contentId = el('content-select').value;
      localStorage.setItem('contentId', state.contentId);
      var current = state.contents.filter(function (c) { return c.id === state.contentId; })[0];
      state.contentStatus = current ? (current.status || 'DRAFT') : 'DRAFT';
      hydrateContentForm(current);
      enqueue(function () {
        return projectApprovalStatus().then(function () { updateReadiness(); });
      }).catch(function (e) { setAlert(e.message); });
    });

    bind('review-action', function () {
      setAlert(''); setStatus('');
      if (!state.contentId) { setAlert('No content selected'); return; }
      enqueue(function () {
        return action({ milestone: 'M6', op: 'approval.review', project_id: state.projectId, content_id: state.contentId })
          .then(function () { setStatus('Content submitted for review'); return loadContents(); });
      }).catch(function (e) { setAlert(e.message); });
    });

    bind('approve-action', function () {
      setAlert(''); setStatus('');
      if (!state.contentId) { setAlert('No content selected'); return; }
      enqueue(function () {
        return action({ milestone: 'M6', op: 'approval.approve', project_id: state.projectId, content_id: state.contentId })
          .then(function () { setStatus('Content approved'); return loadContents(); });
      }).catch(function (e) { setAlert(e.message); });
    });

    bind('publish-action', function () {
      setAlert(''); setStatus('');
      if (!state.contentId) { setAlert('No content selected'); return; }
      enqueue(function () {
        return action({
          milestone: 'M7', op: 'publish.send', project_id: state.projectId,
          content_id: state.contentId, platform_url: el('platform-url').value,
          idempotency_key: 'gui-' + Date.now()
        }).then(function (res) {
          setStatus('Published: ' + (res.status || '') + ' remote_id: ' + (res.remote_id || 'pending'));
          return loadReceipts();
        });
      }).catch(function (e) { setAlert(e.message); });
    });

    bind('schedule-action', function () {
      setAlert(''); setStatus('');
      if (!state.contentId) { setAlert('No content selected'); return; }
      enqueue(function () {
        return action({
          milestone: 'M11', op: 'schedule.create', project_id: state.projectId,
          content_id: state.contentId, when: el('when-input').value
        }).then(function () { setStatus('Scheduled'); return loadSchedules(); });
      }).catch(function (e) { setAlert(e.message); });
    });

    bind('cancel-action', function () {
      setAlert(''); setStatus('');
      if (!state.scheduleId) { setAlert('No schedule selected'); return; }
      enqueue(function () {
        return action({ milestone: 'M11', op: 'schedule.cancel', project_id: state.projectId, schedule_id: state.scheduleId })
          .then(function () { setStatus('Schedule cancelled'); return loadSchedules(); });
      }).catch(function (e) { setAlert(e.message); });
    });

    bind('reschedule-action', function () {
      setAlert(''); setStatus('');
      if (!state.scheduleId) { setAlert('No schedule selected'); return; }
      enqueue(function () {
        return action({ milestone: 'M11', op: 'schedule.reschedule', project_id: state.projectId, schedule_id: state.scheduleId, when: el('when-input').value })
          .then(function () { setStatus('Rescheduled'); return loadSchedules(); });
      }).catch(function (e) { setAlert(e.message); });
    });

    bind('fetch-analytics', function () {
      setAlert(''); setStatus('');
      if (!state.contentId) { setAlert('No content selected'); return; }
      enqueue(function () {
        return action({ milestone: 'M11', op: 'analytics.fetch', project_id: state.projectId, content_id: state.contentId })
          .then(function () { setStatus('Analytics fetched'); return loadAnalytics(); });
      }).catch(function (e) { setAlert(e.message); });
    });

    bind('refresh-receipts', function () {
      setAlert(''); setStatus('');
      enqueue(function () { return loadReceipts(); }).catch(function (e) { setAlert(e.message); });
    });

    bind('refresh-analytics', function () {
      setAlert(''); setStatus('');
      enqueue(function () { return loadAnalytics(); }).catch(function (e) { setAlert(e.message); });
    });

    bind('upload-media-btn', function () {
      setAlert(''); setStatus('');
      var fileInput = el('media-upload');
      if (!fileInput.files || !fileInput.files[0]) {
        setAlert('Please select a file to upload');
        return;
      }
      var file = fileInput.files[0];
      var reader = new FileReader();
      reader.onload = function (e) {
        var base64 = e.target.result.split(',')[1];
        enqueue(function () {
          return action({
            milestone: 'M11', op: 'media.import', project_id: state.projectId,
            filename: file.name, kind: file.type.startsWith('image/') ? 'image' : 'video',
            data: base64
          }).then(function () {
            setStatus('Media uploaded: ' + file.name);
            return loadMedia();
          });
        }).catch(function (err) { setAlert(err.message); });
      };
      reader.readAsDataURL(file);
    });

    var navButtons = document.querySelectorAll('#main-nav button[data-view]');
    Array.prototype.forEach.call(navButtons, function (button) {
      button.addEventListener('click', function () {
        showView(button.getAttribute('data-view'));
        if (button.id === 'nav-content') {
          setAlert(''); setStatus('');
          enqueue(function () {
            return loadClaims().then(loadMedia).then(loadContents);
          }).catch(function (e) { setAlert(e.message); });
        } else if (button.id === 'nav-receipts-analytics') {
          setAlert(''); setStatus('');
          enqueue(function () { return loadReceipts().then(loadAnalytics); }).catch(function (e) { setAlert(e.message); });
        } else if (button.id === 'nav-schedule') {
          enqueue(function () { return loadSchedules(); }).catch(function (e) { setAlert(e.message); });
        }
      });
    });

    refreshAll();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
</script>
</body>
</html>
"""


class RequestHandler(BaseHTTPRequestHandler):
    def _send_json(self, status_code, data):
        self.send_response(status_code)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode('utf-8'))

    def _send_html(self, status_code, html):
        self.send_response(status_code)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.end_headers()
        self.wfile.write(html.encode('utf-8'))

    def _send_bytes(self, status_code, content_type, data):
        self.send_response(status_code)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _serve_media(self, query):
        project_id = (query.get('project_id') or [None])[0]
        media_id = (query.get('media_id') or [None])[0]
        if not project_id or not media_id:
            self._send_json(400, {'error': 'project_id and media_id are required'})
            return
        data_dir = self.server.data_dir
        try:
            meta = m11_handle(data_dir, {
                'milestone': 'M11', 'op': 'media.get',
                'project_id': project_id, 'media_id': media_id
            })
        except ValueError as e:
            self._send_json(404, {'error': str(e)})
            return
        except Exception:
            self._send_json(500, {'error': 'Internal Server Error'})
            return

        if not isinstance(meta, dict):
            self._send_json(500, {'error': 'Invalid media metadata'})
            return
        status = meta.get('status')
        if status != 'VALID':
            self._send_json(404, {'error': 'Media is %s' % (status or 'BROKEN')})
            return

        path = meta.get('path') or meta.get('stored_path') or meta.get('file_path')
        if not path:
            self._send_json(404, {'error': 'Media bytes not found'})
            return
        if not os.path.isabs(path):
            path = os.path.join(data_dir, path)
        try:
            with open(path, 'rb') as fh:
                data = fh.read()
        except OSError:
            self._send_json(404, {'error': 'Media bytes not found'})
            return

        kind = meta.get('kind')
        mime = meta.get('mime') or meta.get('content_type')
        if not mime:
            if kind == 'image':
                mime = 'image/png'
            elif kind == 'video':
                mime = 'video/mp4'
            else:
                mime = 'application/octet-stream'
        self._send_bytes(200, mime, data)

    def _serve_state(self):
        data_dir = self.server.data_dir
        state = {'projects': [], 'campaigns': [], 'contents': [], 'receipts': [], 'schedules': []}
        try:
            state['projects'] = _items(m1_handle(data_dir, {'milestone': 'M1', 'op': 'project.list'}))
        except Exception:
            pass
        try:
            state['campaigns'] = _items(m4_handle(data_dir, {'milestone': 'M4', 'op': 'campaign.list'}))
        except Exception:
            pass
        try:
            state['contents'] = _items(m5_handle(data_dir, {'milestone': 'M5', 'op': 'content.list'}))
        except Exception:
            pass
        try:
            state['receipts'] = _items(m7_handle(data_dir, {'milestone': 'M7', 'op': 'publish.list'}))
        except Exception:
            pass
        try:
            state['schedules'] = _items(m11_handle(data_dir, {'milestone': 'M11', 'op': 'schedule.list'}))
        except Exception:
            pass
        self._send_json(200, state)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)
        if path == '/health':
            self._send_json(200, {'status': 'ok'})
        elif path == '/api/state':
            self._serve_state()
        elif path.startswith('/media/'):
            media_id = path[len('/media/'):]
            if 'media_id' not in query:
                query['media_id'] = [media_id]
            self._serve_media(query)
        elif path == '/api/media':
            self._serve_media(query)
        elif path == '/' or path == '':
            self._send_html(200, INDEX_HTML)
        elif path == '/favicon.ico':
            self.send_response(204)
            self.end_headers()
        else:
            self._send_json(404, {'error': 'Not Found'})

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, HEAD, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_HEAD(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path == '/health':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
        elif path == '/' or path == '':
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
        else:
            self.send_response(404)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path != '/api/action':
            self._send_json(404, {'error': 'Not Found'})
            return

        try:
            content_length = int(self.headers.get('Content-Length', 0))
        except (TypeError, ValueError):
            self._send_json(400, {'error': 'Invalid Content-Length'})
            return
        if content_length < 0:
            self._send_json(400, {'error': 'Invalid Content-Length'})
            return
        post_data = self.rfile.read(content_length)

        try:
            request = json.loads(post_data.decode('utf-8'))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._send_json(400, {'error': 'Invalid JSON'})
            return

        if not isinstance(request, dict):
            self._send_json(400, {'error': 'Request body must be a JSON object'})
            return

        try:
            response = handle(self.server.data_dir, request)
            self._send_json(200, response)
        except ValueError as e:
            self._send_json(400, {'error': str(e)})
        except Exception:
            self._send_json(500, {'error': 'Internal Server Error'})

    def log_message(self, format, *args):
        pass


def _items(result):
    if not result:
        return []
    if isinstance(result, list):
        return result
    if isinstance(result, dict):
        for key in ('items', 'projects', 'campaigns', 'contents', 'receipts', 'schedules', 'claims', 'media'):
            if isinstance(result.get(key), list):
                return result[key]
    return []


class ThreadedHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, host, port, data_dir):
        self.data_dir = data_dir
        super().__init__((host, port), RequestHandler)

    def serve_forever_threaded(self):
        thread = threading.Thread(target=self.serve_forever)
        thread.daemon = True
        thread.start()
        return thread


def main():
    parser = argparse.ArgumentParser(description='Promotion Studio Server')
    parser.add_argument('--serve', action='store_true', help='Start the server')
    parser.add_argument('--port', type=int, default=8080, help='Port to listen on')
    parser.add_argument('--data', type=str, default='./data', help='Data directory')
    args = parser.parse_args()

    if not args.serve:
        print('Usage: python main.py --serve --port PORT --data DIR')
        sys.exit(0)

    os.makedirs(args.data, exist_ok=True)

    server = ThreadedHTTPServer('localhost', args.port, args.data)
    print('Serving on localhost:%d with data dir %s' % (args.port, args.data))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
