export function applyFilters(records, filters) {
  const { streamer, game, category, minScore } = filters;

  return records.filter(record => {
    const matchesStreamer = !streamer || String(record.streamer || '').toLowerCase().includes(streamer.toLowerCase());
    const matchesGame = !game || String(record.game || '').toLowerCase().includes(game.toLowerCase());
    const matchesCategory = !category || String(record.category || '').toLowerCase().includes(category.toLowerCase());
    const matchesScore = !minScore || record.score >= minScore;

    return matchesStreamer && matchesGame && matchesCategory && matchesScore;
  });
}