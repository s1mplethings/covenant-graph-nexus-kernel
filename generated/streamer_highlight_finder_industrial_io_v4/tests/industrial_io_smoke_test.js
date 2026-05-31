window.runIndustrialIOSmokeTest = async function () {
  const storageKey = "cgnk.streamerHighlightFinder.records";
  const wait = (ms = 250) => new Promise((resolve) => setTimeout(resolve, ms));
  const get = (id) => {
    const element = document.getElementById(id);
    if (!element) throw new Error(`Missing DOM id: ${id}`);
    return element;
  };
  const scoreOf = (card) => {
    const text = card.querySelector(".score-badge")?.textContent || "";
    const match = text.match(/-?\d+(?:\.\d+)?/);
    if (!match) throw new Error(`Invalid score text: ${text}`);
    const value = Number(match[0]);
    if (!Number.isFinite(value)) throw new Error(`Score is not numeric: ${text}`);
    return value;
  };

  const [bundle, expected] = await Promise.all([
    fetch("data/industrial_input_bundle.json").then((r) => {
      if (!r.ok) throw new Error("Failed to fetch industrial input bundle");
      return r.json();
    }),
    fetch("data/expected_outputs.json").then((r) => {
      if (!r.ok) throw new Error("Failed to fetch expected outputs");
      return r.json();
    }),
  ]);

  get("json-textarea").value = JSON.stringify(bundle);
  get("import-button").click();
  await wait(500);

  const stored = JSON.parse(localStorage.getItem(storageKey) || "[]");
  if (stored.length < 20) throw new Error(`Expected at least 20 stored records, got ${stored.length}`);
  const sourceIds = new Set(stored.map((row) => row.sourceId || row.source_id || row.source).filter(Boolean));
  if (sourceIds.size < 3) throw new Error(`Expected at least 3 sourceIds, got ${sourceIds.size}`);

  const recordsContainer = get("records-container");
  const cards = Array.from(recordsContainer.querySelectorAll(".highlight-card"));
  if (!cards.length) throw new Error("No visible industrial output cards");
  const scores = cards.map(scoreOf);
  if (!scores.every((score, index) => index === 0 || scores[index - 1] >= score)) {
    throw new Error("Visible industrial scores are not sorted descending");
  }

  const visibleText = recordsContainer.textContent || "";
  const expectedRows = expected.ranked_highlights || expected.top_candidates || [];
  const foundExpected = expectedRows.some((row) => visibleText.includes(row.title || "") || visibleText.includes(row.streamer || ""));
  if (!foundExpected) throw new Error("No expected top ranked title or streamer appears in visible output");

  const firstStreamer = stored.find((row) => row.streamer)?.streamer;
  if (!firstStreamer) throw new Error("No streamer available for filter check");
  get("filterStreamer").value = firstStreamer;
  get("filter-form").dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
  await wait(250);
  const filteredCards = Array.from(recordsContainer.querySelectorAll(".highlight-card"));
  if (!filteredCards.length) throw new Error("Industrial streamer filter produced no visible cards");
  if (!filteredCards.every((card) => (card.querySelector(".metadata-streamer")?.textContent || "").includes(firstStreamer))) {
    throw new Error("Industrial streamer filter showed non-matching cards");
  }
  get("filterStreamer").value = "";
  get("filterGame").value = "";
  get("filterCategory").value = "";
  get("filterScore").value = "";
  get("filter-form").dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
  await wait(250);

  const originalCreateObjectURL = URL.createObjectURL;
  let exportTriggered = false;
  URL.createObjectURL = function (blob) {
    exportTriggered = true;
    return originalCreateObjectURL.call(URL, blob);
  };
  get("export-button").click();
  await wait(100);
  URL.createObjectURL = originalCreateObjectURL;
  if (!exportTriggered) throw new Error("Industrial export did not trigger URL.createObjectURL");

  return { status: "pass", importedCount: stored.length, visibleCount: cards.length, checkedOutputs: expectedRows.length };
};
