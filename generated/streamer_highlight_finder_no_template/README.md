# 游戏主播高光时刻工具

我想要一个可以给我找出游戏主播的高光时刻的项目，可以导入直播事件数据，自动评分和排序，筛选主播、游戏、分类和分数，添加人工标记，导出剪辑清单，并输出测试效果报告

This project was generated from a local Ollama project specification and compiled by CGNK.

## Use

Open `index.html` through a local static server, load sample data or import JSON, adjust filters, add manual markers, and export the current clip list.

## Ollama Spec

```json
{
  "project_type": "ollama_spec_project",
  "title": "游戏主播高光时刻工具",
  "description": "我想要一个可以给我找出游戏主播的高光时刻的项目，可以导入直播事件数据，自动评分和排序，筛选主播、游戏、分类和分数，添加人工标记，导出剪辑清单，并输出测试效果报告",
  "entity_name": "record",
  "fields": [
    {
      "name": "streamer",
      "label": "Streamer",
      "type": "text"
    },
    {
      "name": "game",
      "label": "Game",
      "type": "text"
    },
    {
      "name": "time",
      "label": "Time",
      "type": "text"
    },
    {
      "name": "title",
      "label": "Title",
      "type": "text"
    },
    {
      "name": "category",
      "label": "Category",
      "type": "text"
    },
    {
      "name": "intensity",
      "label": "Intensity",
      "type": "number"
    },
    {
      "name": "chatRate",
      "label": "Chat rate",
      "type": "number"
    },
    {
      "name": "keywords",
      "label": "Keywords",
      "type": "tags"
    },
    {
      "name": "description",
      "label": "Description",
      "type": "text"
    }
  ],
  "filter_fields": [
    "streamer",
    "game",
    "category"
  ],
  "score_fields": [
    "intensity",
    "chatRate"
  ],
  "keyword_boosts": [
    "clutch",
    "ace",
    "win",
    "steal"
  ],
  "sample_records": [
    {
      "streamer": "NovaCarry",
      "game": "Apex Legends",
      "time": "00:03:42",
      "title": "Final ring 1v3 clutch",
      "category": "clutch",
      "intensity": 94,
      "chatRate": 182,
      "keywords": [
        "clutch",
        "win",
        "1v3"
      ],
      "description": "Solo cleanup after a shield swap."
    },
    {
      "streamer": "MapleMage",
      "game": "League of Legends",
      "time": "00:18:09",
      "title": "Baron steal into ace",
      "category": "objective",
      "intensity": 88,
      "chatRate": 150,
      "keywords": [
        "steal",
        "ace",
        "comeback"
      ],
      "description": "Objective steal turns into a teamfight win."
    }
  ],
  "manual_checks": []
}
```
