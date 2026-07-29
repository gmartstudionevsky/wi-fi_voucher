from __future__ import annotations

import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from api.storage import NotEnoughPasswords, PasswordStore


class PasswordStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = PasswordStore(str(Path(self.temp_dir.name) / "vouchers.db"))
        self.store.initialize()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_import_skips_headers_empty_values_and_duplicates(self):
        result = self.store.import_passwords(
            ["Пароль", "", " ABCD-1234 ", "ABCD-1234", "EFGH-5678"]
        )

        self.assertEqual(result["added"], 2)
        self.assertEqual(result["duplicates"], 1)
        self.assertEqual(result["invalid"], 2)
        self.assertEqual(self.store.stats()["available"], 2)

    def test_reservation_can_be_committed(self):
        self.store.import_passwords(["FIRST", "SECOND", "THIRD"])

        reservation = self.store.reserve(2)
        self.assertEqual(reservation.passwords, ("FIRST", "SECOND"))
        self.assertEqual(self.store.stats()["reserved"], 2)

        self.assertEqual(self.store.commit(reservation.batch_id), 2)
        self.assertEqual(self.store.stats()["used"], 2)
        self.assertEqual(
            [item["password"] for item in self.store.list_available()],
            ["THIRD"],
        )

    def test_failed_generation_can_release_reservation(self):
        self.store.import_passwords(["FIRST", "SECOND"])
        reservation = self.store.reserve(2)

        self.assertEqual(self.store.release(reservation.batch_id), 2)
        self.assertEqual(self.store.stats()["available"], 2)
        self.assertEqual(self.store.stats()["reserved"], 0)

    def test_not_enough_passwords_does_not_reserve_anything(self):
        self.store.import_passwords(["ONLY"])

        with self.assertRaises(NotEnoughPasswords) as context:
            self.store.reserve(2)

        self.assertEqual(context.exception.available, 1)
        self.assertEqual(self.store.stats()["available"], 1)
        self.assertEqual(self.store.stats()["reserved"], 0)

    def test_used_password_cannot_be_imported_again(self):
        self.store.import_passwords(["ONCE"])
        reservation = self.store.reserve(1)
        self.store.commit(reservation.batch_id)

        result = self.store.import_passwords(["ONCE"])

        self.assertEqual(result["added"], 0)
        self.assertEqual(result["duplicates"], 1)
        self.assertEqual(self.store.stats()["used"], 1)

    def test_preview_marks_existing_and_in_batch_duplicates(self):
        self.store.import_passwords(["EXISTING"])

        preview = self.store.preview_import(
            ["NEW", "NEW", "EXISTING", "Пароль", ""]
        )

        self.assertEqual(preview["summary"]["new"], 1)
        self.assertEqual(preview["summary"]["duplicates"], 2)
        self.assertEqual(preview["summary"]["invalid"], 2)
        self.assertEqual(
            [item["status"] for item in preview["items"]],
            ["new", "duplicate", "duplicate", "invalid", "invalid"],
        )

    def test_available_password_can_be_edited_but_not_duplicated(self):
        self.store.import_passwords(["FIRST", "SECOND"])
        items = self.store.list_available()

        self.assertTrue(self.store.update_available(items[0]["id"], "UPDATED"))
        self.assertEqual(
            [item["password"] for item in self.store.list_available()],
            ["UPDATED", "SECOND"],
        )

        from api.storage import PasswordConflict

        with self.assertRaises(PasswordConflict):
            self.store.update_available(items[0]["id"], "SECOND")

    def test_issue_marks_selected_passwords_used_atomically(self):
        self.store.import_passwords(["FIRST", "SECOND", "THIRD"])
        items = self.store.list_available()

        issued = self.store.issue_available([items[0]["id"], items[2]["id"]])

        self.assertEqual(issued, ["FIRST", "THIRD"])
        self.assertEqual(self.store.stats()["used"], 2)
        self.assertEqual(
            [item["password"] for item in self.store.list_available()],
            ["SECOND"],
        )
        result = self.store.import_passwords(["FIRST"])
        self.assertEqual(result["duplicates"], 1)

    def test_only_available_password_can_be_deleted(self):
        self.store.import_passwords(["DELETE-ME", "KEEP-HISTORY"])
        items = self.store.list_available()
        self.assertTrue(self.store.delete_available(items[0]["id"]))

        reservation = self.store.reserve(1)
        self.store.commit(reservation.batch_id)
        self.assertFalse(self.store.delete_available(items[1]["id"]))

    def test_concurrent_reservations_never_overlap(self):
        passwords = [f"PASSWORD-{index:03d}" for index in range(100)]
        self.store.import_passwords(passwords)

        with ThreadPoolExecutor(max_workers=10) as executor:
            reservations = list(executor.map(lambda _: self.store.reserve(10), range(10)))

        reserved_passwords = [
            password
            for reservation in reservations
            for password in reservation.passwords
        ]
        self.assertEqual(len(reserved_passwords), 100)
        self.assertEqual(len(set(reserved_passwords)), 100)
        self.assertEqual(self.store.stats()["available"], 0)
        self.assertEqual(self.store.stats()["reserved"], 100)

    def test_restart_releases_expired_reservation(self):
        self.store.import_passwords(["FIRST", "SECOND"])
        self.store.reserve(2)
        with self.store._connection() as connection:
            connection.execute(
                """
                UPDATE passwords
                SET reserved_at = datetime('now', '-20 minutes')
                WHERE hotel_id = ? AND status = 'reserved'
                """,
                (self.store.hotel_id,),
            )

        restarted_store = PasswordStore(str(self.store.database_path))
        restarted_store.initialize()

        self.assertEqual(restarted_store.stats()["available"], 2)
        self.assertEqual(restarted_store.stats()["reserved"], 0)

    def test_hotel_scopes_do_not_leak(self):
        shared_path = str(self.store.database_path)
        other = PasswordStore(shared_path, hotel_id="other", hotel_name="Other")
        other.initialize()
        self.store.import_passwords(["SAME"])
        other.import_passwords(["SAME"])

        self.assertEqual(self.store.stats()["total"], 1)
        self.assertEqual(other.stats()["total"], 1)


if __name__ == "__main__":
    unittest.main()
