"""管理员系统模型设置与显式索引应用接口。"""
from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import require_admin
from app.models import User
from app.schemas.rag_settings import (
    RagSettingsBody, RagSettingsResult, RebuildBody, ServiceTestBody, ServiceTestResult,
)
from app.services import auth, rag_settings

router = APIRouter(prefix="/api/admin/rag-settings", tags=["admin"])


@router.get("", response_model=RagSettingsResult)
def read_settings(
    _user: User = Depends(require_admin), db: Session = Depends(get_db),
) -> RagSettingsResult:
    """读取系统模型、待应用配置、只读 Chroma 状态与重建进度。"""
    return rag_settings.read_settings(db)


@router.put("", response_model=RagSettingsResult)
def save_settings(
    body: RagSettingsBody,
    user: User = Depends(require_admin), db: Session = Depends(get_db),
) -> RagSettingsResult:
    """保存配置；embedding 模型或地址变化须另行重建应用。"""
    auth.assert_version(db, user.id, user.auth_version)
    return rag_settings.save_settings(db, body)


@router.post("/test", response_model=ServiceTestResult)
def test_service(
    body: ServiceTestBody,
    _user: User = Depends(require_admin), db: Session = Depends(get_db),
) -> ServiceTestResult:
    """测试本次模型草稿，不保存输入。"""
    return rag_settings.test_service(db, body)


@router.post("/rebuild", response_model=RagSettingsResult, status_code=202)
def rebuild(
    body: RebuildBody, background: BackgroundTasks,
    user: User = Depends(require_admin), db: Session = Depends(get_db),
) -> RagSettingsResult:
    """提交重建任务；成功后原子切换，失败继续使用旧配置及索引。"""
    auth.assert_version(db, user.id, user.auth_version)
    job_id = rag_settings.queue_rebuild(db, body.revision)
    background.add_task(rag_settings.run_rebuild, job_id)
    return rag_settings.read_settings(db)
