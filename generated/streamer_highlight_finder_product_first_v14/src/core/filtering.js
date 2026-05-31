export function applyFilters(records, filters) {
  const { streamer, game, category, minScore } = filters;

  return records.filter(record => {
    const matchesStreamer = streamer ? String(record.streamer || '').toLowerCase().includes(streamer.toLowerCase()) : true;
    const matchesGame = game ? String(record.game || '').toLowerCase().includes(game.toLowerCase()) : true;
    const matchesCategory = category ? String(record.category || '').toLowerCase().includes(category.toLowerCase()) : true;
    const matchesMinScore = minScore ? record.score >= minScore : true;

    return matchesStreamer && matchesGame && matchesCategory && matchesMinScore;
  });
}