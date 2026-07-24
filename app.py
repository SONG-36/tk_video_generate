from __future__ import annotations

from pathlib import Path

import streamlit as st

from tk_video_generate.config import AppConfig
from tk_video_generate.enums import ProviderName, TaskStatus
from tk_video_generate.repositories.sqlite_repository import RetryNotAllowedError
from tk_video_generate.services.workbench_service import WorkbenchService


@st.cache_resource
def get_service() -> WorkbenchService:
    config = AppConfig.from_env()
    service = WorkbenchService(config)
    service.start_worker()
    return service


def render_create_batch(service: WorkbenchService) -> None:
    st.header("Create Batch")

    if "pending_batch_id" not in st.session_state:
        st.session_state.pending_batch_id = service.new_batch_id()

    batch_id = st.session_state.pending_batch_id

    with st.form("create_batch_form", clear_on_submit=False):
        provider_label = st.selectbox("Provider", options=["Mock", "Seedance"], index=0)
        provider_name = (
            ProviderName.MOCK.value
            if provider_label == "Mock"
            else ProviderName.BYTEPLUS_SEEDANCE.value
        )
        is_real = provider_name != ProviderName.MOCK.value
        confirmation_text = f"CONFIRM REAL {batch_id}" if is_real else f"CONFIRM {batch_id}"
        batch_name = st.text_input("Batch name", value=batch_id)
        concurrency = 1 if is_real else st.slider("Concurrency", min_value=1, max_value=5, value=3)
        duration_seconds = st.selectbox("Duration", options=[3, 5, 10], index=1)
        aspect_ratio = st.selectbox("Aspect ratio", options=["9:16", "1:1", "16:9"], index=0)
        uploads = st.file_uploader(
            "First-frame images (local preview / mock input)",
            type=["png", "jpg", "jpeg"],
            accept_multiple_files=not is_real,
            key=f"uploads-{batch_id}",
        )
        seedance_image_url = None
        if is_real:
            seedance_image_url = st.text_input(
                "Seedance actual first-frame HTTPS URL",
                placeholder="https://example.com/first-frame.png",
            )
            st.caption(
                "Local uploaded image is only a local preview/audit file in real mode. "
                "The Seedance request uses the task-specific HTTPS URL above."
            )
        prompt_text = st.text_area(
            "Prompts, one line per image",
            height=180,
            placeholder=(
                "A cinematic product reveal...\n"
                "[mock-fail] forced failure\n"
                "[mock-timeout] delayed timeout"
            ),
        )

        prompts = [line.strip() for line in prompt_text.splitlines() if line.strip()]
        if is_real and len(prompts) > 1:
            prompts = prompts[:1]
        uploaded_list = uploads if isinstance(uploads, list) else ([uploads] if uploads else [])
        valid_task_count = min(len(uploaded_list), len(prompts), 10) if uploaded_list else 0
        if is_real:
            valid_task_count = min(len(uploaded_list), len(prompts), 1)
        expected_cost = service.estimate_batch_cost(
            valid_task_count,
            duration_seconds,
            provider_name,
        )

        if is_real:
            st.warning("Seedance mode calls a real paid API when configured and confirmed.")
            model_label = service.config.seedance_model or "-"
            st.caption(
                f"Provider Channel: BytePlus ModelArk | Model: {model_label}"
            )
            st.caption(f"API Configuration Status: {service.config.seedance_config_status()}")
            st.caption("Task count: 1 | Concurrency: 1")
            st.caption("费用未知。系统无法在提交前保证实际费用低于填写金额。")
            st.caption(
                f"Operator acknowledgement amount: ${service.config.real_video_max_cost_usd:.2f} "
                "(not a Provider-enforced ceiling)"
            )
            paid_confirmed = st.checkbox(
                "我理解当前费用未知，填写金额不是 Provider 强制消费上限。"
            )
        else:
            paid_confirmed = True
            st.caption(
                f"Valid tasks: {valid_task_count}. Max allowed: 10. "
                f"Estimated mock cost: ${expected_cost:.2f}. Confirmation: `{confirmation_text}`"
            )
        confirmation = st.text_input("Confirmation text", key=f"confirmation-{batch_id}")
        submitted = st.form_submit_button("Submit confirmed batch")

    if not submitted:
        return

    try:
        batch = service.create_confirmed_batch(
            batch_id=batch_id,
            batch_name=batch_name.strip() or batch_id,
            uploaded_files=uploaded_list,
            prompts=prompts,
            duration_seconds=int(duration_seconds),
            aspect_ratio=str(aspect_ratio),
            concurrency_limit=int(concurrency),
            confirmation=confirmation,
            expected_confirmation=confirmation_text,
            provider_name=provider_name,
            real_api_confirmed=paid_confirmed,
            maximum_cost_usd=service.config.real_video_max_cost_usd,
            image_urls=[seedance_image_url] if is_real else None,
        )
    except ValueError as exc:
        st.error(str(exc))
        return

    st.session_state.pending_batch_id = service.new_batch_id()
    st.success(f"Batch {batch.id} queued with {batch.total_tasks} tasks.")
    st.rerun()


def render_task_actions(service: WorkbenchService, task_id: str, status: TaskStatus) -> None:
    task = service.get_task(task_id)
    if task is None:
        return

    if status is TaskStatus.SUCCEEDED and task.output_video_path:
        video_path = Path(task.output_video_path)
        if video_path.exists():
            st.video(str(video_path))
            st.download_button(
                "Download MP4",
                data=video_path.read_bytes(),
                file_name=video_path.name,
                mime="video/mp4",
                key=f"mp4-{task.id}",
            )

    columns = st.columns(3)
    with columns[0]:
        if task.request_json_path and Path(task.request_json_path).exists():
            request_path = Path(task.request_json_path)
            st.download_button(
                "request.json",
                data=request_path.read_bytes(),
                file_name=f"{task.name}_request.json",
                mime="application/json",
                key=f"request-{task.id}",
            )
    with columns[1]:
        if task.result_json_path and Path(task.result_json_path).exists():
            result_path = Path(task.result_json_path)
            st.download_button(
                "result.json",
                data=result_path.read_bytes(),
                file_name=f"{task.name}_result.json",
                mime="application/json",
                key=f"result-{task.id}",
            )
    with columns[2]:
        if status is TaskStatus.FAILED and st.button("Retry", key=f"retry-{task.id}"):
            try:
                service.retry_task(task.id)
                st.rerun()
            except RetryNotAllowedError as exc:
                st.error(str(exc))
        if status in {TaskStatus.SUBMITTED, TaskStatus.POLLING} and st.button(
            "Refresh provider status",
            key=f"poll-{task.id}",
        ):
            service.refresh_task_status(task.id)
            st.rerun()


def render_batches(service: WorkbenchService) -> None:
    st.header("Batches")
    batches = service.list_batches()
    if not batches:
        st.info("No batches yet.")
        return

    for batch in batches:
        tasks = service.list_tasks(batch.id)
        succeeded = sum(task.status is TaskStatus.SUCCEEDED for task in tasks)
        failed = sum(task.status is TaskStatus.FAILED for task in tasks)
        running = sum(task.status is TaskStatus.RUNNING for task in tasks)
        queued = sum(task.status is TaskStatus.QUEUED for task in tasks)

        title = (
            f"{batch.name} - {batch.status.value} - {succeeded} succeeded, "
            f"{failed} failed, {running} running, {queued} queued"
        )
        with st.expander(title, expanded=True):
            zip_path = service.create_batch_zip(batch.id)
            if zip_path and zip_path.exists():
                st.download_button(
                    "Download batch ZIP",
                    data=zip_path.read_bytes(),
                    file_name=zip_path.name,
                    mime="application/zip",
                    key=f"zip-{batch.id}",
                )

            for task in tasks:
                try:
                    status_label = task.status.value
                    st.subheader(f"{task.name} - {status_label}")
                    st.caption(
                        f"Retries: {task.retry_count} | Progress: {task.progress}% | "
                        f"Error: {task.error_code or '-'}"
                    )
                    st.caption(
                        f"Provider: {task.provider} | "
                        f"Provider task: {task.provider_task_id or '-'} | "
                        f"Provider status: {task.provider_status or '-'} | Polls: {task.poll_count}"
                    )
                    st.caption(
                        f"Submitted: {task.submitted_at or '-'} | "
                        f"Last polled: {task.last_polled_at or '-'} | "
                        f"Result URL available: {bool(task.result_url)}"
                    )
                    st.code(task.prompt, language="text")
                    if task.error_message:
                        st.warning(task.error_message)
                    render_task_actions(service, task.id, task.status)
                except Exception as exc:
                    st.error(f"Could not render {task.name}: {exc}")


def main() -> None:
    st.set_page_config(page_title="Mock Video Workbench", layout="wide")
    service = get_service()
    service.start_worker()

    st.title("Batch Video Workbench")
    st.caption(
        "Mock mode is local. Seedance mode is V0.2 single-task real-provider infrastructure."
    )

    render_create_batch(service)
    st.divider()
    render_batches(service)

    if st.button("Refresh"):
        st.rerun()


if __name__ == "__main__":
    main()
