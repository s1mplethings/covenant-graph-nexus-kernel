
let currentProjectId='';const mode="no_empty";
async function list(){let r=await fetch('/api/action',{method:'POST',body:JSON.stringify({op:'project.list'})});let d=await r.json();
 document.getElementById('projects').textContent=d.items.length?d.items[0].name:(mode==='no_empty'?'':'No projects');
 if(mode==='hidden_name')document.getElementById('projects').hidden=true;
 if(d.items.length&&mode!=='lost_selection'){currentProjectId=d.items[0].id;await fetch('/api/state?project_id='+currentProjectId);}
 if(mode==='state_without_id')await fetch('/api/state');
}
async function createProject(){await fetch('/api/action',{method:'POST',body:JSON.stringify({op:'project.create',name:document.getElementById('name').value})});await list();}
list();if(mode==='js_error')setTimeout(()=>{throw new Error('qualification mutation');},10);
