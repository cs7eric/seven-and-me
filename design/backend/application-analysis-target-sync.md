# Application Analysis Target Sync

## 适用范围

- `application-analysis` target 配置
- `self-selected` 中的系统 `target` 分组
- 前端预览态转正式 target 的落盘流程

## 相关代码

- API
  - `backend/api/stock_chart.py`
  - `backend/api/self_selected.py`
- Service / Repo
  - `backend/services/stock/application_analysis_target_sync_service.py`
  - `backend/services/stock/application_analysis_service.py`
  - `backend/services/stock/self_selected_service.py`
  - `backend/repositories/stock/application_analysis_target_repo.py`
  - `backend/repositories/stock/self_selected_repo.py`

## 设计要点

- `application-analysis` 是分析系统的主配置源
- `self-selected` 的系统 `target` 分组是用户可见镜像，不是第二套独立真相
- 前端从自选页跳进分析页时，先进入 preview，不直接写库
- 只有用户确认“加入应用分析”后，才真正写 target，并同步系统分组

## 维护要求

- 改 target 主表、同步方向、去重规则或系统分组初始化逻辑前，先更新本文档
