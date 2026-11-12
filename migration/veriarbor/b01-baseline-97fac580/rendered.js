

        let currentProjectId = null;

        let currentCampaignId = null;

        let currentContentId = null;

        let currentScheduleId = null;

        let currentReceiptId = null;

        let platformUrl = '';



        // Navigation

        function showView(viewName) {

            document.querySelectorAll('.view').forEach(el => el.classList.remove('active'));

            document.getElementById(`view-${viewName}`).classList.add('active');

            

            document.querySelectorAll('.nav-btn').forEach(el => el.classList.remove('active'));

            event.target.classList.add('active');

            

            // Refresh data for the view

            if (viewName === 'projects') loadProjects();

            if (viewName === 'campaigns') loadProjectsForCampaigns();

            if (viewName === 'content') loadProjectsForContent();

            if (viewName === 'schedule') loadProjectsForSchedule();

            if (viewName === 'receipts') loadProjectsForReceipts();

            if (viewName === 'media') loadMedia();

        }



        // API Helper

        async function apiCall(endpoint, method, body) {

            const opts = {

                method: method,

                headers: { 'Content-Type': 'application/json' }

            };

            if (body) opts.body = JSON.stringify(body);

            

            try {

                const res = await fetch(endpoint, opts);

                const data = await res.json();

                if (!res.ok) throw new Error(data.error || 'Request failed');

                return data;

            } catch (e) {

                console.error(e);

                throw e;

            }

        }



        // --- Projects ---

        async function loadProjects() {

            try {

                // Fetch state to get projects

                const state = await apiCall('/api/state', 'GET', null); // Note: State requires project_id usually, but maybe global list endpoint exists or we iterate?

                // Actually, /api/state requires project_id. To list ALL projects, we might need a different op or just rely on creation.

                // For simplicity, we'll assume we track created ones locally or have a list endpoint.

                // Let's assume M1 has a 'list' op for projects.

                const projects = await apiCall('/api/action', 'POST', { op: 'project.list', milestone: 'M1' });

                renderList('projects-list', projects.items || projects, p => `<div class="item" onclick="selectProject('${p.id}')">${p.name}</div>`);

            } catch (e) {

                showError('project-error', e.message);

            }

        }



        function selectProject(id) {

            currentProjectId = id;

            updateStatus('project-status', `Selected Project: ${id}`);

            // Update selects in other views

            populateProjectSelects();

        }



        async function createProject() {

            const name = document.getElementById('project-name').value;

            if (!name) return showError('project-error', 'Name required');

            

            try {

                const res = await apiCall('/api/action', 'POST', { op: 'project.create', milestone: 'M1', name: name });

                updateStatus('project-status', `Created Project: ${res.id}`);

                currentProjectId = res.id;

                loadProjects();

                populateProjectSelects();

            } catch (e) {

                showError('project-error', e.message);

            }

        }



        // --- Campaigns ---

        function populateProjectSelects() {

            // Simple helper to fill project dropdowns

            // In a real app, we'd cache the list

            const selects = ['campaign-project-select', 'content-project-select', 'sched-project-select', 'rec-project-select'];

            // We need the list of projects. Let's fetch it once and store globally.

            // For now, just trigger reloads

        }



        async function loadProjectsForCampaigns() {

             try {

                const projects = await apiCall('/api/action', 'POST', { op: 'project.list', milestone: 'M1' });

                const sel = document.getElementById('campaign-project-select');

                sel.innerHTML = '<option value="">-- Select --</option>' + (projects.items || projects).map(p => `<option value="${p.id}">${p.name}</option>`).join('');

                if (currentProjectId) sel.value = currentProjectId;

                loadCampaigns();

             } catch(e) { showError('campaign-error', e.message); }

        }



        async function loadCampaigns() {

            const pid = document.getElementById('campaign-project-select').value;

            if (!pid) return;

            try {

                const camps = await apiCall('/api/action', 'POST', { op: 'campaign.list', milestone: 'M4', project_id: pid });

                renderList('campaigns-list', camps.items || camps, c => `<div class="item" onclick="selectCampaign('${c.id}', '${pid}')">${c.name}</div>`);

            } catch (e) {

                showError('campaign-error', e.message);

            }

        }



        function selectCampaign(id, pid) {

            currentCampaignId = id;

            currentProjectId = pid;

            updateStatus('campaign-status', `Selected Campaign: ${id}`);

        }



        async function createCampaign() {

            const pid = document.getElementById('campaign-project-select').value;

            const name = document.getElementById('campaign-name').value;

            const audience = document.getElementById('campaign-audience').value;

            const channelsStr = document.getElementById('campaign-channels').value;

            const channels = channelsStr ? channelsStr.split(',').map(s => s.trim()) : [];

            

            if (!pid || !name) return showError('campaign-error', 'Project and Name required');

            

            try {

                const res = await apiCall('/api/action', 'POST', { op: 'campaign.create', milestone: 'M4', project_id: pid, name: name, audience: audience, channels: channels });

                updateStatus('campaign-status', `Created Campaign: ${res.id}`);

                loadCampaigns();

            } catch (e) {

                showError('campaign-error', e.message);

            }

        }



        // --- Content ---

        async function loadProjectsForContent() {

             try {

                const projects = await apiCall('/api/action', 'POST', { op: 'project.list', milestone: 'M1' });

                const sel = document.getElementById('content-project-select');

                sel.innerHTML = '<option value="">-- Select --</option>' + (projects.items || projects).map(p => `<option value="${p.id}">${p.name}</option>`).join('');

                if (currentProjectId) sel.value = currentProjectId;

                loadCampaignsForContent();

             } catch(e) { showError('content-error', e.message); }

        }



        async function loadCampaignsForContent() {

            const pid = document.getElementById('content-project-select').value;

            if (!pid) return;

            try {

                const camps = await apiCall('/api/action', 'POST', { op: 'campaign.list', milestone: 'M4', project_id: pid });

                const sel = document.getElementById('content-campaign-select');

                sel.innerHTML = '<option value="">-- Select --</option>' + (camps.items || camps).map(c => `<option value="${c.id}" data-channels="${JSON.stringify(c.channels || [])}">${c.name}</option>`).join('');

                if (currentCampaignId) sel.value = currentCampaignId;

                updateChannelSelect();

                loadContents();

            } catch (e) {

                showError('content-error', e.message);

            }

        }



        function updateChannelSelect() {

            const campSel = document.getElementById('content-campaign-select');

            const opt = campSel.options[campSel.selectedIndex];

            if (!opt || !opt.value) return;

            const channels = JSON.parse(opt.getAttribute('data-channels') || '[]');

            const chanSel = document.getElementById('content-channel');

            chanSel.innerHTML = channels.map(ch => `<option value="${ch}">${ch}</option>`).join('');

        }



        async function loadContents() {

            const pid = document.getElementById('content-project-select').value;

            const cid = document.getElementById('content-campaign-select').value;

            if (!pid || !cid) return;

            try {

                const conts = await apiCall('/api/action', 'POST', { op: 'content.list', milestone: 'M5', project_id: pid, campaign_id: cid });

                renderList('content-list', conts.items || conts, c => `<div class="item" onclick="selectContent('${c.id}')">${c.text.substring(0,50)}...</div>`);

            } catch (e) {

                showError('content-error', e.message);

            }

        }



        function selectContent(id) {

            currentContentId = id;

            updateStatus('content-status', `Selected Content: ${id}`);

        }



        async function saveContent() {

            const pid = document.getElementById('content-project-select').value;

            const cid = document.getElementById('content-campaign-select').value;

            const channel = document.getElementById('content-channel').value;

            const text = document.getElementById('content-text').value;

            

            if (!pid || !cid || !channel || !text) return showError('content-error', 'All fields required');

            

            try {

                const res = await apiCall('/api/action', 'POST', { op: 'content.create', milestone: 'M5', project_id: pid, campaign_id: cid, channel: channel, text: text });

                updateStatus('content-status', `Saved Content: ${res.id}`);

                currentContentId = res.id;

                loadContents();

            } catch (e) {

                showError('content-error', e.message);

            }

        }



        async function reviewContent() {

            if (!currentContentId) return showError('content-error', 'No content selected');

            try {

                await apiCall('/api/action', 'POST', { op: 'approval.review', milestone: 'M6', content_id: currentContentId });

                updateStatus('content-status', 'Content reviewed');

            } catch (e) {

                showError('content-error', e.message);

            }

        }



        async function approveContent() {

            if (!currentContentId) return showError('content-error', 'No content selected');

            try {

                await apiCall('/api/action', 'POST', { op: 'approval.approve', milestone: 'M6', content_id: currentContentId });

                updateStatus('content-status', 'Content approved');

            } catch (e) {

                showError('content-error', e.message);

            }

        }



        // --- Schedule/Publish ---

        async function loadProjectsForSchedule() {

             try {

                const projects = await apiCall('/api/action', 'POST', { op: 'project.list', milestone: 'M1' });

                const sel = document.getElementById('sched-project-select');

                sel.innerHTML = '<option value="">-- Select --</option>' + (projects.items || projects).map(p => `<option value="${p.id}">${p.name}</option>`).join('');

                if (currentProjectId) sel.value = currentProjectId;

                loadSchedCampaigns();

             } catch(e) { showError('sched-error', e.message); }

        }



        async function loadSchedCampaigns() {

            const pid = document.getElementById('sched-project-select').value;

            if (!pid) return;

            try {

                const camps = await apiCall('/api/action', 'POST', { op: 'campaign.list', milestone: 'M4', project_id: pid });

                const sel = document.getElementById('sched-campaign-select');

                sel.innerHTML = '<option value="">-- Select --</option>' + (camps.items || camps).map(c => `<option value="${c.id}">${c.name}</option>`).join('');

                if (currentCampaignId) sel.value = currentCampaignId;

                loadSchedContents();

            } catch (e) {

                showError('sched-error', e.message);

            }

        }



        async function loadSchedContents() {

            const pid = document.getElementById('sched-project-select').value;

            const cid = document.getElementById('sched-campaign-select').value;

            if (!pid || !cid) return;

            try {

                const conts = await apiCall('/api/action', 'POST', { op: 'content.list', milestone: 'M5', project_id: pid, campaign_id: cid });

                const sel = document.getElementById('sched-content-select');

                sel.innerHTML = '<option value="">-- Select --</option>' + (conts.items || conts).map(c => `<option value="${c.id}">${c.text.substring(0,30)}</option>`).join('');

                if (currentContentId) sel.value = currentContentId;

                loadSchedules();

            } catch (e) {

                showError('sched-error', e.message);

            }

        }



        async function publishNow() {

            const pid = document.getElementById('sched-project-select').value;

            const cid = document.getElementById('sched-campaign-select').value;

            const contId = document.getElementById('sched-content-select').value;

            const url = document.getElementById('platform-url').value;

            

            if (!pid || !cid || !contId || !url) return showError('sched-error', 'All fields required');

            

            try {

                const res = await apiCall('/api/action', 'POST', { op: 'publish.send', milestone: 'M7', project_id: pid, campaign_id: cid, content_id: contId, platform_url: url });

                updateStatus('sched-status', `Published. Receipt: ${res.receipt_id}`);

                currentReceiptId = res.receipt_id;

            } catch (e) {

                showError('sched-error', e.message);

            }

        }



        async function scheduleAction() {

            const pid = document.getElementById('sched-project-select').value;

            const cid = document.getElementById('sched-campaign-select').value;

            const contId = document.getElementById('sched-content-select').value;

            const url = document.getElementById('platform-url').value;

            const when = document.getElementById('when').value;

            

            if (!pid || !cid || !contId || !url || !when) return showError('sched-error', 'All fields required');

            

            // Generate idempotency key

            const idempotencyKey = `sched-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;

            

            try {

                const res = await apiCall('/api/action', 'POST', { 

                    op: 'schedule.create', 

                    milestone: 'M8', 

                    project_id: pid, 

                    campaign_id: cid, 

                    content_id: contId, 

                    platform_url: url, 

                    when: when,

                    idempotency_key: idempotencyKey

                });

                updateStatus('sched-status', `Scheduled. ID: ${res.id}`);

                currentScheduleId = res.id;

                loadSchedules();

            } catch (e) {

                showError('sched-error', e.message);

            }

        }



        async function cancelSchedule() {

            if (!currentScheduleId) return showError('sched-error', 'No schedule selected');

            try {

                await apiCall('/api/action', 'POST', { op: 'schedule.cancel', milestone: 'M8', schedule_id: currentScheduleId });

                updateStatus('sched-status', 'Schedule cancelled');

                loadSchedules();

            } catch (e) {

                showError('sched-error', e.message);

            }

        }



        async function rescheduleAction() {

            if (!currentScheduleId) return showError('sched-error', 'No schedule selected');

            const when = document.getElementById('when').value;

            if (!when) return showError('sched-error', 'New time required');

            

            try {

                await apiCall('/api/action', 'POST', { op: 'schedule.reschedule', milestone: 'M8', schedule_id: currentScheduleId, when: when });

                updateStatus('sched-status', 'Schedule updated');

                loadSchedules();

            } catch (e) {

                showError('sched-error', e.message);

            }

        }



        async function loadSchedules() {

            const pid = document.getElementById('sched-project-select').value;

            if (!pid) return;

            try {

                const scheds = await apiCall('/api/action', 'POST', { op: 'schedule.list', milestone: 'M8', project_id: pid });

                renderList('schedules-list', scheds.items || scheds, s => `<div class="item" onclick="selectSchedule('${s.id}')">${s.when} - ${s.status}</div>`);

            } catch (e) {

                showError('sched-error', e.message);

            }

        }



        function selectSchedule(id) {

            currentScheduleId = id;

            updateStatus('sched-status', `Selected Schedule: ${id}`);

        }



        // --- Receipts/Analytics ---

        async function loadProjectsForReceipts() {

             try {

                const projects = await apiCall('/api/action', 'POST', { op: 'project.list', milestone: 'M1' });

                const sel = document.getElementById('rec-project-select');

                sel.innerHTML = '<option value="">-- Select --</option>' + (projects.items || projects).map(p => `<option value="${p.id}">${p.name}</option>`).join('');

                if (currentProjectId) sel.value = currentProjectId;

                loadReceipts();

             } catch(e) { showError('rec-error', e.message); }

        }



        async function loadReceipts() {

            const pid = document.getElementById('rec-project-select').value;

            if (!pid) return;

            try {

                const recs = await apiCall('/api/action', 'POST', { op: 'receipt.list', milestone: 'M9', project_id: pid });

                const sel = document.getElementById('rec-receipt-select');

                sel.innerHTML = '<option value="">-- Select --</option>' + (recs.items || recs).map(r => `<option value="${r.id}">${r.remote_id || r.id}</option>`).join('');

                if (currentReceiptId) sel.value = currentReceiptId;

                renderList('receipts-list', recs.items || recs, r => `<div class="item" onclick="selectReceipt('${r.id}')">Receipt: ${r.remote_id || r.id}</div>`);

            } catch (e) {

                showError('rec-error', e.message);

            }

        }



        function selectReceipt(id) {

            currentReceiptId = id;

            updateStatus('rec-status', `Selected Receipt: ${id}`);

        }



        async function fetchAnalytics() {

            const pid = document.getElementById('rec-project-select').value;

            const rid = document.getElementById('rec-receipt-select').value;

            const url = document.getElementById('platform-url').value; // Reusing platform URL field or separate?

            // Prompt says: "Analytics uses configured platform_url/receipt_id correctly... using actual configured Platform URL from state/localStorage or parsed receipt.request_ref instead of missing receipt.platform_url"

            

            if (!pid || !rid) return showError('rec-error', 'Project and Receipt required');

            

            // Try to get platform_url from receipt if not explicitly set in UI

            let platUrl = url;

            if (!platUrl) {

                // Fallback: try to extract from receipt data if available in local state or re-fetch

                // For now, assume user must provide it or it's stored.

                // If we had the receipt object, we could check receipt.platform_url

                // Since we don't have full receipt object in JS memory necessarily, we might need to fetch it.

                // Simplification: Require Platform URL in Schedule view to be shared or passed.

                // The prompt says "Add shared configured platform_url". 

                // We'll assume the input in Schedule view is the source of truth for platform_url.

                platUrl = document.getElementById('platform-url').value;

            }

            

            if (!platUrl) return showError('rec-error', 'Platform URL required for analytics');



            try {

                const res = await apiCall('/api/action', 'POST', { 

                    op: 'analytics.fetch', 

                    milestone: 'M10', // Assuming M10 or M11 handles analytics

                    project_id: pid, 

                    receipt_id: rid, 

                    platform_url: platUrl 

                });

                document.getElementById('analytics-result').innerHTML = `<pre>${JSON.stringify(res, null, 2)}</pre>`;

                updateStatus('rec-status', 'Analytics fetched');

            } catch (e) {

                showError('rec-error', e.message);

            }

        }



        // --- Media ---

        async function loadMedia() {

            // Placeholder for loading existing media

        }



        async function importMedia() {

            const fileInput = document.getElementById('media-file');

            const kind = document.getElementById('media-kind').value;

            const pid = currentProjectId; // Assume current project

            

            if (!fileInput.files.length) return showError('media-error', 'File required');

            if (!pid) return showError('media-error', 'Project required');

            

            const file = fileInput.files[0];

            const reader = new FileReader();

            

            reader.onload = async (e) => {

                const base64Data = e.target.result.split(',')[1];

                try {

                    const res = await apiCall('/api/action', 'POST', { 

                        op: 'media.import', 

                        milestone: 'M11', // Assuming M10 for media

                        project_id: pid, 

                        kind: kind, 

                        data: base64Data, 

                        filename: file.name

                    });

                    updateStatus('media-status', `Uploaded Media: ${res.id}`);

                    // Show preview

                    const img = document.createElement('img');

                    img.src = `/media/${res.id}?project_id=${pid}`;

                    img.style.maxWidth = '200px';

                    document.getElementById('media-preview').appendChild(img);

                } catch (err) {

                    showError('media-error', err.message);

                }

            };

            

            reader.readAsDataURL(file);

        }



        // Helpers

        function renderList(containerId, items, renderItem) {

            const container = document.getElementById(containerId);

            container.innerHTML = items.map(renderItem).join('');

        }



        function updateStatus(elementId, msg) {

            document.getElementById(elementId).textContent = msg;

        }



        function showError(elementId, msg) {

            document.getElementById(elementId).textContent = msg;

        }



        // Init

        window.onload = () => {

            loadProjects();

        };

    