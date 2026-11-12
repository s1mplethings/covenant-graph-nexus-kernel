
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
    if (el('publish-action-schedule')) el('publish-action-schedule').disabled = !hasContent || !isApproved;
    if (el('schedule-action')) el('schedule-action').disabled = !hasContent || !isApproved;
    if (el('cancel-action')) el('cancel-action').disabled = !state.scheduleId;
    if (el('reschedule-action')) el('reschedule-action').disabled = !state.scheduleId;
    if (el('fetch-analytics')) el('fetch-analytics').disabled = !state.projectId || !state.receipts.length;
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

  function clearContentForm() {
    if (el('content-text')) el('content-text').value = '';
    if (el('content-channel')) el('content-channel').selectedIndex = -1;
    if (el('content-claims')) Array.prototype.forEach.call(el('content-claims').options, function(o){o.selected=false;});
    if (el('content-media')) Array.prototype.forEach.call(el('content-media').options, function(o){o.selected=false;});
    if (el('content-select')) el('content-select').selectedIndex = -1;
    state.contentId = null;
    state.contentStatus = null;
    state.approvalStatus = null;
    renderContentMediaPreview(null);
    updateReadiness();
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
      updateReadiness();
      return items;
    }).catch(function () { return []; });
  }

  function loadSchedules() {
    if (!state.projectId) {
      state.schedules = [];
      if (el('schedule-list')) el('schedule-list').innerHTML = '';
      return Promise.resolve([]);
    }
    return action({ milestone: 'M8', op: 'schedule.list', project_id: state.projectId }).then(function (res) {
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
      // Auto-select first schedule if none selected
      if (items.length && !state.scheduleId) {
         state.scheduleId = items[0].id;
      }
      updateReadiness();
      return items;
    }).catch(function () { return []; });
  }

  function loadAnalytics() {
    if (!state.projectId) {
      el('analytics-list').innerHTML = '';
      return Promise.resolve([]);
    }
    return action({ milestone: 'M10', op: 'analytics.history', project_id: state.projectId }).then(function (res) {
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

  function doPublish(urlInputId) {
    setAlert(''); setStatus('');
    if (!state.contentId) { setAlert('No content selected'); return; }
    var urlNode = el(urlInputId);
    var platformUrl = urlNode ? urlNode.value : '';
    enqueue(function () {
      return action({
        milestone: 'M7', op: 'publish.send', project_id: state.projectId,
        content_id: state.contentId, platform_url: platformUrl,
        idempotency_key: 'gui-' + Date.now()
      }).then(function (res) {
        setStatus('Published: ' + (res.status || '') + ' remote_id: ' + (res.remote_id || 'pending'));
        return loadReceipts();
      });
    }).catch(function (e) { setAlert(e.message); });
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
      
      var payload = {
        milestone: 'M5',
        project_id: state.projectId,
        campaign_id: state.campaignId,
        text: el('content-text').value,
        channel: el('content-channel').value,
        claim_ids: claimIds,
        media_ids: mediaIds
      };

      if (state.contentId) {
        payload.op = 'content.edit';
        payload.content_id = state.contentId;
      } else {
        payload.op = 'content.create';
      }

      enqueue(function () {
        return action(payload).then(function (res) {
          setStatus('Saved content: ' + (res.id || ''));
          return loadContents();
        });
      }).catch(function (e) { setAlert(e.message); });
    });

    bind('new-content-btn', function () {
       clearContentForm();
       setStatus('Ready for new content');
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

    bind('publish-action', function () { doPublish('platform-url'); });
    bind('publish-action-schedule', function () { doPublish('platform-url-schedule'); });

    bind('schedule-action', function () {
      setAlert(''); setStatus('');
      if (!state.contentId) { setAlert('No content selected'); return; }
      enqueue(function () {
        return action({
          milestone: 'M8', op: 'schedule.create', project_id: state.projectId,
          content_id: state.contentId, when: el('when-input').value
        }).then(function () { setStatus('Scheduled'); return loadSchedules(); });
      }).catch(function (e) { setAlert(e.message); });
    });

    bind('cancel-action', function () {
      setAlert(''); setStatus('');
      if (!state.scheduleId) { setAlert('No schedule selected'); return; }
      enqueue(function () {
        return action({ milestone: 'M8', op: 'schedule.cancel', project_id: state.projectId, schedule_id: state.scheduleId })
          .then(function () { setStatus('Schedule cancelled'); return loadSchedules(); });
      }).catch(function (e) { setAlert(e.message); });
    });

    bind('reschedule-action', function () {
      setAlert(''); setStatus('');
      if (!state.scheduleId) { setAlert('No schedule selected'); return; }
      enqueue(function () {
        return action({ milestone: 'M8', op: 'schedule.reschedule', project_id: state.projectId, schedule_id: state.scheduleId, when: el('when-input').value })
          .then(function () { setStatus('Rescheduled'); return loadSchedules(); });
      }).catch(function (e) { setAlert(e.message); });
    });

    bind('fetch-analytics', function () {
      setAlert(''); setStatus('');
      if (!state.projectId) { setAlert('No project selected'); return; }
      if (!state.receipts || state.receipts.length === 0) { setAlert('No receipts found to fetch analytics for'); return; }
      
      // Fetch analytics for the most recent receipt
      var receipt = state.receipts[state.receipts.length - 1];
      var receiptId = receipt.id;
      var platformUrl = receipt.platform_url || '';
      
      enqueue(function () {
        return action({
          milestone: 'M10', op: 'analytics.fetch', project_id: state.projectId, receipt_id: receiptId, platform_url: platformUrl
        }).then(function () { 
            setStatus('Analytics fetched for receipt ' + receiptId);
            return loadAnalytics(); 
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
            filename: file.name, kind: file.type.indexOf('image/') === 0 ? 'image' : 'video',
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
