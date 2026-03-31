name: Daily News Push

on:
  schedule:
    # 每天 UTC 01:00 = 北京时间 09:00
    - cron: '0 1 * * *'
  workflow_dispatch:  # 手动触发（测试用）

jobs:
  push-news:
    runs-on: ubuntu-latest
    
    steps:
      - name: Checkout code
        uses: actions/checkout@v4
      
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      
      - name: Run news fetch and push
        working-directory: ${{ github.workspace }}
        env:
          WXPUSHER_APP_TOKEN: ${{ secrets.WXPUSHER_APP_TOKEN }}
          WXPUSHER_UID: ${{ secrets.WXPUSHER_UID }}
        run: |
          pwd
          ls -la
          python fetch_news.py
