import { useCallback, useEffect, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { apiGet } from "../api";
import QcStagesEditor from "../components/QcStagesEditor";
import { Message, TableSkeleton } from "../components/Feedback";
import type { ProductMasterRow } from "../types";

/**
 * A product, as its batch record reads: each QC stage in order, with what it asks
 * for inside it. A batch-record stage shows its steps and check points; a stage
 * tested in the lab shows its tests and limits, and the product's specification
 * shows inside the stages that use it.
 */
export default function ProductDetail() {
  const { id } = useParams();
  // Opened on one stage's tests (?tests=final%20grain): that stage opens them.
  const [params] = useSearchParams();
  const focus = params.get("tests");
  const [product, setProduct] = useState<ProductMasterRow | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      setProduct(await apiGet<ProductMasterRow>(`/api/product-master/${id}/`));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load this product.");
    }
  }, [id]);

  useEffect(() => {
    void load();
  }, [load]);

  if (error) return <Message kind="error">{error}</Message>;
  if (!product) return <div className="card"><div className="card-body flush"><TableSkeleton /></div></div>;

  return (
    <>
      <div className="breadcrumb"><Link to="/admin/products">Products</Link> / {product.code}</div>
      <div className="page-head">
        <h1>{product.name}</h1>
        <p className="sub">
          {[product.dosage_form, product.strength, product.section_name].filter(Boolean).join(" · ")}
          {" · "}<Link to={`/batches?product=${product.id}`}>{product.batch_count ?? "See"} batches</Link>
        </p>
      </div>
      <QcStagesEditor productId={product.id} focus={focus} />
    </>
  );
}
