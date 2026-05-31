export function applyFilters(records, filters) {
  const { streamer, game, category, minScore } = filters;

  return records.filter(record => {
    const matchesStreamer = streamer ? String(record.streamer || '').toLowerCase().includes(String(streamer).toLowerCase()) : true;
    const matchesGame = game ? String(record.game || '').toLowerCase().includes(String(game).toLowerCase()) : true;
    const matchesCategory = category ? String(record.category || '').toLowerCase().includes(String(category).toLowerCase()) : true;
    const matchesMinScore = minScore ? (record.score || 0) >= minScore : true;

    return matchesStreamer && matchesGame && matchesCategory && matchesMinScore;
  });
}