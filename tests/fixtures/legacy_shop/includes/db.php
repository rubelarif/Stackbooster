<?php
// Database connection shared by every page.
$DB_HOST = 'localhost';
$DB_NAME = 'shop';

$conn = mysqli_connect($DB_HOST, 'shop_user', getenv('SHOP_DB_PASSWORD'), $DB_NAME);
if (!$conn) {
    die('Database connection failed');
}

function db_all($conn, $sql) {
    $result = mysqli_query($conn, $sql);
    $rows = array();
    while ($row = mysqli_fetch_assoc($result)) {
        $rows[] = $row;
    }
    return $rows;
}

function cart_total($conn, $session_id) {
    $sql = "SELECT SUM(p.price * c.quantity) AS total FROM cart_items c JOIN products p ON p.id = c.product_id WHERE c.session_id = '$session_id'";
    $rows = db_all($conn, $sql);
    return $rows ? $rows[0]['total'] : 0;
}
