# Changelog

所有重要变更记录在此文件。版本发布建议遵循 Semantic Versioning。

## Unreleased

### Changed

- 将仓库整理为 `apps/`、`services/`、`ml/`、`tools/`、`docs/`、`scripts/`、`artifacts/`、`legacy/` 和 `.workspace/` 分层结构。
- 用户数据库和运行文件默认迁移到 `.workspace/`。
- 统一用户端、监管端、识别服务和 Rokid 后端的路径配置。
- 增加开发、测试、架构、运行和协作规范文档。

### Compatibility

- 根目录 `start_rokid_backend.ps1` 继续保留，并转发到新的规范脚本。
- 迁移前的 `recognition_algorithm` 嵌套仓库完整保存在 `legacy/recognition-algorithm-repository/`。
