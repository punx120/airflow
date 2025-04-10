#
# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.
from __future__ import annotations

import os
from unittest.mock import MagicMock, Mock, PropertyMock, patch

import pytest

from airflow.providers.apache.hive.transfers.hive_to_samba import HiveToSambaOperator
from airflow.providers.samba.hooks.samba import SambaHook

from tests_common.test_utils.version_compat import AIRFLOW_V_3_0_PLUS
from unit.apache.hive import (
    DEFAULT_DATE,
    MockConnectionCursor,
    MockHiveServer2Hook,
    TestHiveEnvironment,
)

if AIRFLOW_V_3_0_PLUS:
    from airflow.sdk.execution_time.context import context_to_airflow_vars
else:
    from airflow.utils.operator_helpers import context_to_airflow_vars  # type: ignore[no-redef, attr-defined]


class MockSambaHook(SambaHook):
    def __init__(self, *args, **kwargs):
        self.conn = MockConnectionCursor()
        self.conn.execute = MagicMock()
        self.get_conn = MagicMock(return_value=self.conn)
        super().__init__(*args, **kwargs)

    def get_connection(self, *args):
        return self.conn


class TestHive2SambaOperator(TestHiveEnvironment):
    def setup_method(self, method):
        self.kwargs = dict(
            hql="hql",
            destination_filepath="destination_filepath",
            samba_conn_id="samba_default",
            hiveserver2_conn_id="hiveserver2_default",
            task_id="test_hive_to_samba_operator",
        )
        super().setup_method(method)

    @patch("airflow.providers.apache.hive.transfers.hive_to_samba.SambaHook")
    @patch("airflow.providers.apache.hive.transfers.hive_to_samba.HiveServer2Hook")
    @patch("airflow.providers.apache.hive.transfers.hive_to_samba.NamedTemporaryFile")
    def test_execute(self, mock_tmp_file, mock_hive_hook, mock_samba_hook):
        type(mock_tmp_file).name = PropertyMock(return_value="tmp_file")
        mock_tmp_file.return_value.__enter__ = Mock(return_value=mock_tmp_file)
        context = {}

        HiveToSambaOperator(**self.kwargs).execute(context)

        mock_hive_hook.assert_called_once_with(hiveserver2_conn_id=self.kwargs["hiveserver2_conn_id"])
        mock_hive_hook.return_value.to_csv.assert_called_once_with(
            self.kwargs["hql"],
            csv_filepath=mock_tmp_file.name,
            hive_conf=context_to_airflow_vars(context),
        )
        mock_samba_hook.assert_called_once_with(samba_conn_id=self.kwargs["samba_conn_id"])
        mock_samba_hook.return_value.push_from_local.assert_called_once_with(
            self.kwargs["destination_filepath"], mock_tmp_file.name
        )

    @pytest.mark.skipif(
        "AIRFLOW_RUNALL_TESTS" not in os.environ, reason="Skipped because AIRFLOW_RUNALL_TESTS is not set"
    )
    @patch("tempfile.tempdir", "/tmp/")
    @patch("tempfile._RandomNameSequence.__next__")
    @patch(
        "airflow.providers.apache.hive.transfers.hive_to_samba.HiveServer2Hook",
        side_effect=MockHiveServer2Hook,
    )
    def test_hive2samba(self, mock_hive_server_hook, mock_temp_dir):
        mock_temp_dir.return_value = "tst"

        samba_hook = MockSambaHook(self.kwargs["samba_conn_id"])
        samba_hook.upload = MagicMock()

        with patch(
            "airflow.providers.apache.hive.transfers.hive_to_samba.SambaHook", return_value=samba_hook
        ):
            samba_hook.conn.upload = MagicMock()
            op = HiveToSambaOperator(
                task_id="hive2samba_check",
                samba_conn_id="tableau_samba",
                hql="SELECT * FROM airflow.static_babynames LIMIT 10000",
                destination_filepath="test_airflow.csv",
                dag=self.dag,
            )
            op.run(start_date=DEFAULT_DATE, end_date=DEFAULT_DATE, ignore_ti_state=True)

        samba_hook.conn.upload.assert_called_with("/tmp/tmptst", "test_airflow.csv")
