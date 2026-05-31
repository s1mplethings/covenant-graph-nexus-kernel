window.runIndustrialIOSmokeTest = async function () {
  const wait = (ms = 120) => new Promise((resolve) => setTimeout(resolve, ms));
  const get = (id) => {
    const node = document.getElementById(id);
    if (!node) throw new Error(`missing #${id}`);
    return node;
  };
  const [bundle, expected] = await Promise.all([
    fetch("data/industrial_input_bundle.json").then((response) => response.json()),
    fetch("data/expected_outputs.json").then((response) => response.json()),
  ]);
  if (!bundle.video || expected.input_summary.requiredInput !== "GameVideoFile") {
    throw new Error("fixture must describe a single GameVideoFile input");
  }
  get("min-score").value = "0";
  get("min-score").dispatchEvent(new Event("input", { bubbles: true }));
  get("load-synthetic").click();
  await wait();
  const cards = Array.from(document.querySelectorAll(".candidate"));
  if (cards.length < 3) throw new Error("video fixture produced too few candidates");
  const scores = cards.map((card) => Number(card.querySelector(".score")?.textContent || "0"));
  for (let i = 1; i < scores.length; i += 1) {
    if (scores[i] > scores[i - 1]) throw new Error("industrial scores are not sorted descending");
  }
  const text = get("candidate-list").textContent.toLowerCase();
  if (!expected.ranked_highlights.some((row) => text.includes(row.category))) throw new Error("expected category is not visible");
  let exported = false;
  const originalCreateObjectURL = URL.createObjectURL;
  URL.createObjectURL = function (blob) {
    exported = blob instanceof Blob;
    return "blob:industrial-cut-list";
  };
  try {
    get("export-cutlist").click();
  } finally {
    URL.createObjectURL = originalCreateObjectURL;
  }
  if (!exported) throw new Error("industrial export did not create Blob URL");
  return { status: "pass", input: expected.input_summary.requiredInput, visibleCount: cards.length };
};
