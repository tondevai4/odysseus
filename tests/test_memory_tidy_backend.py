from services.memory.tidy import apply_local_tidy, plan_local_tidy


class FakeMemoryManager:
    def __init__(self, rows):
        self.rows = list(rows)
        self.saved = None

    def load(self, owner=None):
        if owner is None:
            return list(self.rows)
        return [row for row in self.rows if row.get("owner") == owner]

    def load_all(self):
        return list(self.rows)

    def save(self, rows):
        self.saved = list(rows)
        self.rows = list(rows)


class FakeVector:
    healthy = True

    def __init__(self):
        self.rebuilt = None

    def rebuild(self, rows):
        self.rebuilt = list(rows)


def test_plan_local_tidy_removes_empty_and_exact_duplicates():
    plan = plan_local_tidy([
        {"id": "a", "text": "  User likes Python.  ", "category": "preference", "source": "user"},
        {"id": "b", "text": "User likes Python.", "category": "preference", "source": "auto"},
        {"id": "c", "text": "", "category": "fact", "source": "auto"},
        {"id": "d", "text": "User likes carpentry.", "category": "preference", "source": "auto"},
    ])

    assert plan["before"] == 4
    assert plan["after"] == 2
    assert set(plan["removed_ids"]) == {"b", "c"}
    assert plan["final_entries"][0]["id"] == "a"
    assert plan["final_entries"][0]["text"] == "User likes Python."


def test_plan_local_tidy_preserves_distinct_related_facts():
    plan = plan_local_tidy([
        {"id": "a", "text": "User likes Python.", "category": "preference"},
        {"id": "b", "text": "User uses Python at work.", "category": "fact"},
    ])

    assert plan["after"] == 2
    assert plan["removed_ids"] == []


def test_apply_local_tidy_is_owner_scoped_and_rebuilds_vector():
    manager = FakeMemoryManager([
        {"id": "a", "text": "User likes tea.", "category": "preference", "owner": "alice"},
        {"id": "b", "text": "User likes tea.", "category": "preference", "owner": "alice"},
        {"id": "c", "text": "User likes coffee.", "category": "preference", "owner": "bob"},
    ])
    vector = FakeVector()

    result = apply_local_tidy(manager, vector, owner="alice")

    assert result["before"] == 2
    assert result["after"] == 1
    assert result["removed"] == 1
    assert [row["id"] for row in manager.rows] == ["a", "c"]
    assert [row["id"] for row in vector.rebuilt] == ["a", "c"]
