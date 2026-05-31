const STORAGE_KEY = "cgnk.localTaskBoard.tasks";
const statuses = ["todo", "doing", "done"];

function loadTasks() {
  try {
    const parsed = JSON.parse(localStorage.getItem(STORAGE_KEY) || "[]");
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function saveTasks(tasks) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(tasks));
}

function seedTasks() {
  return [
    { id: crypto.randomUUID(), title: "Review customer request", status: "todo" },
    { id: crypto.randomUUID(), title: "Generate blueprint", status: "doing" },
    { id: crypto.randomUUID(), title: "Emit test graph", status: "done" },
  ];
}

let tasks = loadTasks();
if (!tasks.length) {
  tasks = seedTasks();
  saveTasks(tasks);
}

function moveTask(id, direction) {
  const task = tasks.find((item) => item.id === id);
  if (!task) return;
  const index = statuses.indexOf(task.status);
  const next = Math.max(0, Math.min(statuses.length - 1, index + direction));
  task.status = statuses[next];
  saveTasks(tasks);
  render();
}

function deleteTask(id) {
  tasks = tasks.filter((item) => item.id !== id);
  saveTasks(tasks);
  render();
}

function render() {
  for (const status of statuses) {
    const target = document.getElementById(status);
    target.innerHTML = "";
    tasks.filter((task) => task.status === status).forEach((task) => {
      const card = document.createElement("article");
      card.className = "card";
      card.innerHTML = `
        <p>${task.title}</p>
        <div class="card-actions">
          <button type="button" data-action="left">Left</button>
          <button type="button" data-action="right">Right</button>
          <button type="button" data-action="delete">Delete</button>
        </div>`;
      card.querySelector('[data-action="left"]').addEventListener("click", () => moveTask(task.id, -1));
      card.querySelector('[data-action="right"]').addEventListener("click", () => moveTask(task.id, 1));
      card.querySelector('[data-action="delete"]').addEventListener("click", () => deleteTask(task.id));
      target.appendChild(card);
    });
  }
}

document.getElementById("taskForm").addEventListener("submit", (event) => {
  event.preventDefault();
  const title = document.getElementById("taskTitle").value.trim();
  const status = document.getElementById("taskStatus").value;
  if (!title) return;
  tasks.push({ id: crypto.randomUUID(), title, status });
  saveTasks(tasks);
  event.target.reset();
  render();
});

document.getElementById("addSeed").addEventListener("click", () => {
  tasks = tasks.concat(seedTasks());
  saveTasks(tasks);
  render();
});

render();
