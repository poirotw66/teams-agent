import assert from "node:assert/strict";
import test from "node:test";

import {
  assignWorkHubBuckets,
  partitionQualityCases,
} from "../../src/ai_ops_backoffice/static/js/views/workHubBuckets.js";

test("unassigned open cases stay out of mine and review", () => {
  const partitioned = partitionQualityCases(
    [
      {
        case_id: "case-other",
        title: "其他人的案件",
        status: "IN_PROGRESS",
        assignee_id: "someone-else",
      },
    ],
    "ops.admin",
  );
  const buckets = assignWorkHubBuckets({
    mineCaseRows: partitioned.mineItems,
    trackingCaseRows: partitioned.trackingItems,
  });

  assert.equal(partitioned.mineItems.length, 0);
  assert.equal(buckets.mineRows.length, 0);
  assert.equal(buckets.reviewRows.length, 0);
  assert.equal(buckets.trackingRows.length, 0);
});

test("assigned and observing cases stay in their own buckets", () => {
  const partitioned = partitionQualityCases(
    [
      {
        case_id: "case-mine",
        status: "WAITING_REVIEW",
        assignee_id: "Ops.Admin",
      },
      {
        case_id: "case-watch",
        status: "OBSERVING",
        assignee_id: "other",
      },
    ],
    "ops.admin",
  );
  const buckets = assignWorkHubBuckets({
    pendingReviewRows: [{ title: "待審文件", kind: "item", status: "待審核" }],
    mineCaseRows: partitioned.mineItems,
    trackingCaseRows: partitioned.trackingItems,
  });

  assert.deepEqual(
    partitioned.mineItems.map((item) => item.case_id),
    ["case-mine"],
  );
  assert.deepEqual(
    partitioned.trackingItems.map((item) => item.case_id),
    ["case-watch"],
  );
  assert.equal(buckets.reviewRows.length, 1);
  assert.equal(buckets.reviewRows[0].title, "待審文件");
});
