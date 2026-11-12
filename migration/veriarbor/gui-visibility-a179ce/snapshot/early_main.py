"""Milestone M7: Early Main GUI Backend.

Provides a browser-based GUI backend that dispatches requests to milestone modules (M1-M7).
Supports the workflow: Projects -> Campaign -> Content -> Review/Approve -> Local Publish -> Receipts.
"""

import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

# Import milestone handlers
try:
    from milestones.milestone_20f2614f6ae8403d4a4e.api import handle as m1_handle
except ImportError:
    def m1_handle(data_dir, request):
        raise ValueError("M1 module not found")

try:
    from milestones.milestone_4e7c26281cf61a85851e.api import handle as m2_handle
except ImportError:
    def m2_handle(data_dir, request):
        raise ValueError("M2 module not found")

try:
    from milestones.milestone_1369a82cde04a7e5887d.api import handle as m3_handle
except ImportError:
    def m3_handle(data_dir, request):
        raise ValueError("M3 module not found")

try:
    from milestones.milestone_90b8868c7203e2958397.api import handle as m4_handle
except ImportError:
    def m4_handle(data_dir, request):
        raise ValueError("M4 module not found")

try:
    from milestones.milestone_9165a990eed5b9c8801e.api import handle as m5_handle
except ImportError:
    def m5_handle(data_dir, request):
        raise ValueError("M5 module not found")

try:
    from milestones.milestone_33270fed0c9054f5ae04.api import handle as m6_handle
except ImportError:
    def m6_handle(data_dir, request):
        raise ValueError("M6 module not found")

try:
    from promotion_publish import handle as m7_handle
except ImportError:
    def m7_handle(data_dir, request):
        raise ValueError("M7 module not found")


HANDLERS = {
    "M1": m1_handle,
    "M2": m2_handle,
    "M3": m3_handle,
    "M4": m4_handle,
    "M5": m5_handle,
    "M6": m6_handle,
    "M7": m7_handle,
}

OP_PREFIX_MAP = {
    "project.": "M1",
    "evidence.": "M2",
    "signal.": "M2",
    "claim.": "M3",
    "campaign.": "M4",
    "content.": "M5",
    "approval.": "M6",
    "publish.": "M7",
}


def _infer_milestone(request):
    """Determine the milestone id from an explicit 'milestone' field or the 'op' prefix."""
    milestone_id = request.get("milestone")
    if isinstance(milestone_id, str) and milestone_id:
        return milestone_id
    op = request.get("op")
    if isinstance(op, str) and op:
        for prefix, mid in OP_PREFIX_MAP.items():
            if op.startswith(prefix):
                return mid
    return None


def handle(data_dir, request):
    """
    Dispatches a request to the appropriate milestone handler based on 'milestone' field or 'op' prefix.

    Args:
        data_dir (str): The directory for persistent storage.
        request (dict): Must contain 'milestone' (str) OR 'op' (str), and other operation-specific fields.

    Returns:
        dict: The result from the specific milestone handler.

    Raises:
        ValueError: If 'milestone'/'op' is missing, invalid, or if the underlying handler raises an error.
    """
    if not isinstance(data_dir, str) or not data_dir:
        raise ValueError("data_dir must be a non-empty string")
    if not isinstance(request, dict):
        raise ValueError("request must be a dict")

    milestone_id = _infer_milestone(request)
    if not isinstance(milestone_id, str) or not milestone_id:
        raise ValueError("request must contain a non-empty 'milestone' string or a recognized 'op' prefix")

    handler = HANDLERS.get(milestone_id)
    if not handler:
        raise ValueError("Unknown milestone: %s" % milestone_id)

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
</style>
</head>
<body>
<h1>Promotion Studio</h1>
<nav id="main-nav" aria-label="Primary">
  <button id="nav-projects" type="button" data-view="projects-view">Projects</button>
  <button id="nav-campaigns" type="button" data-view="campaigns-view">Campaigns</button>
  <button id="nav-content" type="button" data-view="content-view">Content</button>
  <button id="nav-review" type="button" data-view="review-view">Review</button>
  <button id="nav-publish" type="button" data-view="publish-view">Publish</button>
  <button id="nav-receipts-analytics" type="button" data-view="receipts-analytics-view">Receipts/Analytics</button>
</nav>
<div id="alert" role="alert"></div>
<div id="status" role="status"></div>

<section id="projects-view" class="view active">
  <h2>Projects</h2>
  <label for="project-name">Project name</label>
  <input id="project-name" type="text">
  <button id="create-project" type="button" data-action="project.create">Create project</button>
  <label for="project-select">Select project</label>
  <select id="project-select"></select>
  <span id="current-project-name" class="context-name"></span>
</section>

<section id="campaigns-view" class="view">
  <h2>Campaigns</h2>
  <label for="campaign-name">Campaign name</label>
  <input id="campaign-name" type="text">
  <label for="campaign-audience">Audience</label>
  <input id="campaign-audience" type="text">
  <label for="campaign-channels">Channels</label>
  <input id="campaign-channels" type="text" placeholder="comma-separated">
  <button id="create-campaign" type="button" data-action="campaign.create">Create campaign</button>
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
  <button id="save-content" type="button" data-action="content.create">Save content</button>
  <button id="refresh-content" type="button" data-action="content.refresh">Refresh content</button>
  <label for="content-select">Select content</label>
  <select id="content-select"></select>
</section>

<section id="review-view" class="view">
  <h2>Review / Approve</h2>
  <button id="review-action" type="button" data-action="approval.review">Review</button>
  <button id="approve-action" type="button" data-action="approval.approve">Approve</button>
</section>

<section id="publish-view" class="view">
  <h2>Publish</h2>
  <label for="platform-url">Platform URL</label>
  <input id="platform-url" type="text">
  <button id="publish-action" type="button" data-action="publish.send">Publish</button>
</section>

<section id="receipts-analytics-view" class="view">
  <h2>Receipts</h2>
  <button id="refresh-receipts" type="button" data-action="receipts.refresh">Refresh receipts</button>
  <ul id="receipt-list"></ul>
  <h2>Analytics</h2>
  <button id="refresh-analytics" type="button" data-action="analytics.refresh">Refresh analytics</button>
  <ul id="analytics-list"></ul>
</section>

<script>
(function () {
  'use strict';

  var state = {
    projectId: null,
    campaignId: null,
    contentId: null,
    projects: [],
    campaigns: [],
    claims: [],
    contents: [],
    receipts: [],
    contentStatus: null,
    approvalStatus: null,
    actionQueue: Promise.resolve(),
    busy: false,
    workflowState: 'idle'
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
    if (Array.isArray(result.receipts)) return result.receipts;
    return [];
  }

  function fillSelect(select, items, idKey, labelKey) {
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
    var views = ['projects-view', 'campaigns-view', 'content-view', 'review-view', 'publish-view', 'receipts-analytics-view'];
    views.forEach(function (id) {
      var node = el(id);
      if (node) node.classList.remove('active');
    });
    var target = el(viewId);
    if (target) target.classList.add('active');
  }

  // Reveal the real review/publish sections alongside the active content view so
  // the actual #review-action/#approve-action/#publish-action controls are
  // reachable (not hidden) while the Content workflow is active.
  function revealWorkflowSections() {
    var hasContent = !!state.contentId;
    var reviewView = el('review-view');
    var publishView = el('publish-view');
    if (reviewView) {
      if (hasContent) {
        reviewView.classList.add('active');
      } else {
        reviewView.classList.remove('active');
      }
    }
    if (publishView) {
      if (hasContent && state.approvalStatus === 'APPROVED') {
        publishView.classList.add('active');
      } else {
        publishView.classList.remove('active');
      }
    }
  }

  function updateReadiness() {
    var hasProject = !!state.projectId;
    var hasCampaign = !!state.campaignId;
    var hasContent = !!state.contentId;

    // Align with backend contract values DRAFT/REVIEW/APPROVED
    var isDraft = state.contentStatus === 'DRAFT';
    var isReviewed = state.approvalStatus === 'REVIEW';
    var isApproved = state.approvalStatus === 'APPROVED';

    el('create-campaign').disabled = !hasProject;
    el('save-content').disabled = !hasProject || !hasCampaign;

    // Review action enabled when content exists and is in DRAFT status
    el('review-action').disabled = !hasContent || !isDraft;

    // Approve action enabled when content exists and is in REVIEW status
    el('approve-action').disabled = !hasContent || !isReviewed;

    // Publish action enabled when content exists and is in APPROVED status
    el('publish-action').disabled = !hasContent || !isApproved;

    // Keep the action controls visible and reachable outside nav regions.
    // The Review/Approve/Publish buttons live in the main content area so the
    // qualified locator (button named Review, not inside nav) resolves them.
    var actionBar = el('action-bar');
    if (actionBar) {
      actionBar.hidden = false;
    }
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
      el('content-channel').innerHTML = '';
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
        el('content-channel').innerHTML = '';
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
    });
  }

  function loadContents() {
    if (!state.projectId) {
      state.contents = [];
      fillSelect(el('content-select'), [], 'id', 'text');
      state.contentId = null;
      state.contentStatus = null;
      state.approvalStatus = null;
      state.workflowState = 'idle';
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
        
        // Extract distinct statuses
        state.contentStatus = current ? (current.status || 'DRAFT') : 'DRAFT';
        state.approvalStatus = current ? (current.approval_status || null) : null;
        
        // Sync workflow state loosely based on status for UI readiness
        if (state.approvalStatus === 'APPROVED') {
          state.workflowState = 'approve_complete';
        } else if (state.approvalStatus === 'REVIEW') {
          state.workflowState = 'review_complete';
        } else {
          state.workflowState = 'content_ready';
        }
      } else {
        state.contentId = null;
        state.contentStatus = null;
        state.approvalStatus = null;
        state.workflowState = 'idle';
      }
      updateReadiness();
      return items;
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
    });
  }

  function loadAnalytics() {
    if (!state.projectId) {
      el('analytics-list').innerHTML = '';
      return Promise.resolve([]);
    }
    return action({ milestone: 'M7', op: 'publish.list', project_id: state.projectId }).then(function (res) {
      var items = itemsOf(res);
      var list = el('analytics-list');
      list.innerHTML = '';
      var counts = {};
      items.forEach(function (r) {
        var s = r.status || 'UNKNOWN';
        counts[s] = (counts[s] || 0) + 1;
      });
      Object.keys(counts).forEach(function (k) {
        var li = document.createElement('li');
        li.textContent = k + ': ' + counts[k];
        list.appendChild(li);
      });
      return items;
    });
  }

  function refreshContent() {
    return loadClaims().then(loadContents);
  }

  function refreshAll() {
    return loadProjects()
      .then(loadCampaigns)
      .then(loadClaims)
      .then(loadContents)
      .then(loadReceipts)
      .catch(function (e) { setAlert(e.message); });
  }

  function bind(id, handler) {
    var node = el(id);
    if (node) node.addEventListener('click', handler);
  }

  function auditDuplicateIds() {
    var ids = {};
    var duplicates = [];
    var all = document.querySelectorAll('[id]');
    all.forEach(function (node) {
      var id = node.id;
      if (ids[id]) {
        duplicates.push(id);
      } else {
        ids[id] = true;
      }
    });
    if (duplicates.length) {
      throw new Error('Duplicate DOM IDs: ' + duplicates.join(', '));
    }
  }

  function init() {
    try {
      auditDuplicateIds();
    } catch (e) {
      setAlert(e.message);
      return;
    }

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
        return loadCampaigns().then(loadClaims).then(loadContents).then(loadReceipts);
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
      updateReadiness();
    });

    bind('save-content', function () {
      setAlert(''); setStatus('');
      var claimId = el('content-claims').value;
      var claimIds = claimId ? [claimId] : [];
      enqueue(function () {
        return action({
          milestone: 'M5', op: 'content.create', project_id: state.projectId,
          campaign_id: state.campaignId, text: el('content-text').value,
          channel: el('content-channel').value, claim_ids: claimIds
        }).then(function (res) {
          setStatus('Saved content: ' + (res.id || ''));
          // Force reload to get correct ID and status from server
          return loadContents();
        });
      }).catch(function (e) { setAlert(e.message); });
    });

    bind('refresh-content', function () {
      setAlert(''); setStatus('');
      enqueue(function () {
        return refreshContent();
      }).then(function () { setStatus('Content refreshed'); }).catch(function (e) { setAlert(e.message); });
    });

    el('content-select').addEventListener('change', function () {
      state.contentId = el('content-select').value;
      localStorage.setItem('contentId', state.contentId);
      var current = state.contents.filter(function (c) { return c.id === state.contentId; })[0];
      state.contentStatus = current ? (current.status || 'DRAFT') : 'DRAFT';
      state.approvalStatus = current ? (current.approval_status || null) : null;
      
      if (state.approvalStatus === 'APPROVED') {
        state.workflowState = 'approve_complete';
      } else if (state.approvalStatus === 'REVIEW') {
        state.workflowState = 'review_complete';
      } else {
        state.workflowState = 'content_ready';
      }
      updateReadiness();
    });

    bind('review-action', function () {
      setAlert(''); setStatus('');
      if (!state.contentId) {
        setAlert('No content selected');
        return;
      }
      enqueue(function () {
        return action({ milestone: 'M6', op: 'approval.review', project_id: state.projectId, content_id: state.contentId })
          .then(function () {
            setStatus('Content submitted for review');
            // Reload contents to sync status from backend
            return loadContents();
          });
      }).catch(function (e) { setAlert(e.message); });
    });

    bind('approve-action', function () {
      setAlert(''); setStatus('');
      if (!state.contentId) {
        setAlert('No content selected');
        return;
      }
      enqueue(function () {
        return action({ milestone: 'M6', op: 'approval.approve', project_id: state.projectId, content_id: state.contentId })
          .then(function () {
            setStatus('Content approved');
            // Reload contents to sync status from backend
            return loadContents();
          });
      }).catch(function (e) { setAlert(e.message); });
    });

    bind('publish-action', function () {
      setAlert(''); setStatus('');
      if (!state.contentId) {
        setAlert('No content selected');
        return;
      }
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

    bind('refresh-receipts', function () {
      setAlert(''); setStatus('');
      enqueue(function () { return loadReceipts(); }).catch(function (e) { setAlert(e.message); });
    });

    bind('refresh-analytics', function () {
      setAlert(''); setStatus('');
      enqueue(function () { return loadAnalytics(); }).catch(function (e) { setAlert(e.message); });
    });

    var navButtons = document.querySelectorAll('#main-nav button[data-view]');
    navButtons.forEach(function (button) {
      button.addEventListener('click', function () {
        showView(button.getAttribute('data-view'));
        if (button.id === 'nav-content') {
          setAlert(''); setStatus('');
          enqueue(function () { return refreshContent(); }).then(function () { setStatus('Content refreshed'); }).catch(function (e) { setAlert(e.message); });
        } else if (button.id === 'nav-receipts-analytics') {
          setAlert(''); setStatus('');
          enqueue(function () { return loadReceipts(); }).catch(function (e) { setAlert(e.message); });
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
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode("utf-8"))

    def _send_html(self, status_code, html):
        self.send_response(status_code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html.encode("utf-8"))

    def do_GET(self):
        if self.path == "/health":
            self._send_json(200, {"status": "ok"})
        elif self.path == "/" or self.path.startswith("/?"):
            self._send_html(200, INDEX_HTML)
        elif self.path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
        else:
            self._send_json(404, {"error": "Not Found"})

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, HEAD, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_HEAD(self):
        if self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
        elif self.path == "/" or self.path.startswith("/?"):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
        else:
            self.send_response(404)
            self.send_header("Content-Type", "application/json")
            self.end_headers()

    def do_POST(self):
        if self.path != "/api/action":
            self._send_json(404, {"error": "Not Found"})
            return

        try:
            content_length = int(self.headers.get("Content-Length", 0))
        except (TypeError, ValueError):
            self._send_json(400, {"error": "Invalid Content-Length"})
            return
        if content_length < 0:
            self._send_json(400, {"error": "Invalid Content-Length"})
            return
        post_data = self.rfile.read(content_length)

        try:
            request = json.loads(post_data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._send_json(400, {"error": "Invalid JSON"})
            return

        if not isinstance(request, dict):
            self._send_json(400, {"error": "Request body must be a JSON object"})
            return

        data_dir = self.server.data_dir

        try:
            response = handle(data_dir, request)
            self._send_json(200, response)
        except ValueError as e:
            self._send_json(400, {"error": str(e)})
        except Exception as e:
            self._send_json(500, {"error": "Internal Server Error: %s" % str(e)})

    def log_message(self, format, *args):
        pass


class ThreadedHTTPServer(HTTPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, host, port, data_dir):
        super().__init__((host, port), RequestHandler)
        self.data_dir = data_dir

    def serve_forever_threaded(self):
        thread = threading.Thread(target=self.serve_forever)
        thread.daemon = True
        thread.start()
        return thread


def main():
    if len(sys.argv) < 2:
        print("Usage: python early_main.py --serve --port PORT --data DIR")
        sys.exit(0)

    args = sys.argv[1:]
    if "--serve" not in args:
        print("Usage: python early_main.py --serve --port PORT --data DIR")
        sys.exit(0)

    port = 8080
    data_dir = "./data"

    try:
        if "--port" in args:
            idx = args.index("--port")
            port = int(args[idx + 1])
        if "--data" in args:
            idx = args.index("--data")
            data_dir = args[idx + 1]
    except (IndexError, ValueError):
        print("Invalid arguments")
        sys.exit(1)

    os.makedirs(data_dir, exist_ok=True)

    server = ThreadedHTTPServer("localhost", port, data_dir)
    print("Serving on localhost:%d with data dir %s" % (port, data_dir))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()