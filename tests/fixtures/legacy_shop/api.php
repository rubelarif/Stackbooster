<?php
/*
 * AJAX endpoint used by the storefront.
 * Every action returns JSON.
 */
session_start();
require_once 'includes/db.php';
header('Content-Type: application/json');

$action = isset($_REQUEST['action']) ? $_REQUEST['action'] : '';
$sid = session_id();

switch ($action) {
    case 'add_to_cart':
        $product_id = (int)$_POST['product_id'];
        $qty = max(1, (int)$_POST['quantity']);
        mysqli_query($conn, "INSERT INTO cart_items (session_id, product_id, quantity) VALUES ('$sid', $product_id, $qty) ON DUPLICATE KEY UPDATE quantity = quantity + $qty");
        $rows = db_all($conn, "SELECT SUM(quantity) AS n FROM cart_items WHERE session_id = '$sid'");
        echo json_encode(array('ok' => true, 'count' => (int)$rows[0]['n']));
        break;

    case 'remove_from_cart':
        $item_id = (int)$_POST['item_id'];
        mysqli_query($conn, "DELETE FROM cart_items WHERE id = $item_id AND session_id = '$sid'");
        echo json_encode(array('ok' => true));
        break;

    case 'cart_count':
        $rows = db_all($conn, "SELECT SUM(quantity) AS n FROM cart_items WHERE session_id = '$sid'");
        echo json_encode(array('count' => (int)$rows[0]['n']));
        break;

    case 'search':
    case 'autocomplete':
        $term = mysqli_real_escape_string($conn, $_GET['q']);
        $rows = db_all($conn, "SELECT id, name FROM products WHERE name LIKE '%$term%' LIMIT 10");
        echo json_encode($rows);
        break;

    default:
        http_response_code(400);
        echo json_encode(array('error' => 'unknown action'));
}
