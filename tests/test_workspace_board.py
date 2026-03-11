from agent_os.core.workspace import CollaborationBoard, WorkItem


def test_collaboration_board_ready_items_and_mailbox() -> None:
    first = WorkItem(title="Inspect", owner="coder", goal="Inspect repo", priority=1)
    second = WorkItem(title="Write", owner="writer", goal="Write summary", depends_on=[first.item_id], priority=2)
    review = WorkItem(title="Review", owner="reviewer", goal="Review outputs", depends_on=[second.item_id], priority=3)

    board = CollaborationBoard(task_id="task1", goal="Ship feature")
    board.add_item(first)
    board.add_item(second)
    board.add_item(review)

    ready_before = board.ready_items()
    assert [item.item_id for item in ready_before] == [first.item_id]

    board.send_message("planner", "coder", "Start with repository inspection", first.item_id)
    inbox = board.inbox_for("coder")
    assert inbox[-1]["content"] == "Start with repository inspection"

    first.status = "done"
    ready_after = board.ready_items()
    assert [item.item_id for item in ready_after] == [second.item_id]

    board.approve_plan()
    assert board.plan_status == "approved"
    assert all(item.approved for item in board.items)
